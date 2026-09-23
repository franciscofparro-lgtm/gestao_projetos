"""Lógica do registo de horas.

Funções puras, sem Streamlit nem acesso ao Google Sheets: recebem DataFrames
e devolvem DataFrames ou planos de escrita. Assim podem ser testadas
isoladamente e as páginas limitam-se a apresentar e gravar.

Unidade interna: minutos inteiros (coluna duracao_min). As horas decimais
só aparecem na interface e nos relatórios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd

from lib.config import (
    ALERTA_ORCAMENTO,
    ARREDONDAMENTO_MIN,
    HORAS_SEMANA_OMISSAO,
    LIMITE_HORAS_REGISTO,
)

SEM_TAREFA = "(geral)"


# ==========================================================================
# Utilitários
# ==========================================================================
def arredondar(minutos: float, minimo: bool = True) -> int:
    """Arredonda ao múltiplo de ARREDONDAMENTO_MIN mais próximo.

    Com minimo=True, qualquer valor positivo fica com pelo menos um passo
    (um temporizador de 3 minutos conta 15, não 0).
    """
    if minutos is None or pd.isna(minutos) or minutos <= 0:
        return 0
    passo = ARREDONDAMENTO_MIN
    valor = int(round(minutos / passo)) * passo
    if minimo and valor == 0:
        valor = passo
    return valor


def sim(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in {"sim", "true", "1", "s", "yes"}


def para_date(valor) -> date | None:
    if valor is None or (not isinstance(valor, (date, datetime)) and pd.isna(valor)):
        return None
    if isinstance(valor, pd.Timestamp):
        return None if pd.isna(valor) else valor.date()
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return pd.Timestamp(valor).date()
    except Exception:  # noqa: BLE001
        return None


def para_time(valor) -> time | None:
    if valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, time):
        return valor.replace(second=0, microsecond=0)
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.time().replace(second=0, microsecond=0)
    try:
        h, m = str(valor).strip().split(":")[:2]
        return time(int(h), int(m))
    except Exception:  # noqa: BLE001
        return None


def minutos_entre(inicio: time, fim: time) -> int:
    """Minutos entre duas horas; se fim < início assume passagem da meia-noite."""
    a = inicio.hour * 60 + inicio.minute
    b = fim.hour * 60 + fim.minute
    if b < a:
        b += 24 * 60
    return b - a


def fmt_horas(minutos: float) -> str:
    """120 -> '2:00'; 75 -> '1:15'."""
    minutos = int(round(minutos or 0))
    return f"{minutos // 60}:{minutos % 60:02d}"


def segunda(d: date) -> date:
    return d - timedelta(days=d.weekday())


def dias_da_semana(seg: date) -> list[date]:
    return [seg + timedelta(days=i) for i in range(7)]


def tags_lista(texto) -> list[str]:
    if not texto or (isinstance(texto, float) and pd.isna(texto)):
        return []
    return [t.strip() for t in str(texto).split(",") if t.strip()]


def tags_texto(lista) -> str:
    vistos, saida = set(), []
    for t in lista or []:
        t = str(t).strip()
        if t and t.lower() not in vistos:
            vistos.add(t.lower())
            saida.append(t)
    return ", ".join(saida)


# ==========================================================================
# Atividades (projeto + tarefa) como rótulo único
# ==========================================================================
def rotulos_atividade(
    projetos: pd.DataFrame,
    tarefas: pd.DataFrame,
    incluir_ids: set[tuple[str, str]] | None = None,
    so_ativos: bool = True,
) -> tuple[dict[str, tuple[str, str]], dict[tuple[str, str], str]]:
    """Constrói rótulos «CÓDIGO · Tarefa» para seleção numa única coluna.

    Devolve (rótulo -> (projeto_id, tarefa_id), (projeto_id, tarefa_id) -> rótulo).
    Projetos não ativos só aparecem se estiverem em incluir_ids (registos
    já existentes que é preciso continuar a mostrar).
    """
    incluir_ids = incluir_ids or set()
    incluir_proj = {p for p, _ in incluir_ids}
    por_rotulo: dict[str, tuple[str, str]] = {}
    por_chave: dict[tuple[str, str], str] = {}

    if projetos.empty:
        return por_rotulo, por_chave

    def _registar(rotulo: str, chave: tuple[str, str]) -> None:
        base, n = rotulo, 2
        while rotulo in por_rotulo:
            rotulo = f"{base} ({n})"
            n += 1
        por_rotulo[rotulo] = chave
        por_chave[chave] = rotulo

    for _, p in projetos.sort_values(["codigo", "nome"]).iterrows():
        pid = p["id"]
        ativo = str(p.get("estado", "")) in {"Ativo", ""}
        if so_ativos and not ativo and pid not in incluir_proj:
            continue
        prefixo = str(p.get("codigo") or "").strip() or str(p["nome"])
        _registar(f"{prefixo} · {SEM_TAREFA}", (pid, ""))
        if not tarefas.empty:
            dele = tarefas[tarefas["projeto_id"] == pid]
            for _, t in dele.sort_values("nome").iterrows():
                chave = (pid, t["id"])
                concluida = str(t.get("estado", "")) == "Concluída"
                if so_ativos and concluida and chave not in incluir_ids:
                    continue
                _registar(f"{prefixo} · {t['nome']}", chave)

    # Chaves referidas por registos mas já inexistentes (tarefa apagada)
    for chave in incluir_ids:
        if chave not in por_chave:
            _registar(f"[removido] {chave[0]} · {chave[1] or SEM_TAREFA}", chave)

    return por_rotulo, por_chave


# ==========================================================================
# Taxas
# ==========================================================================
def taxa_aplicavel(
    projeto_id: str,
    membro_id: str,
    taxas: pd.DataFrame,
    projetos: pd.DataFrame,
    membros: pd.DataFrame,
) -> float:
    """Taxa de faturação por ordem de precedência:
    específica (projeto × membro) > do projeto > do membro > 0.
    """
    if not taxas.empty:
        esp = taxas[(taxas["projeto_id"] == projeto_id) & (taxas["membro_id"] == membro_id)]
        if not esp.empty and float(esp.iloc[0]["taxa_hora"]) > 0:
            return float(esp.iloc[0]["taxa_hora"])
    if not projetos.empty:
        p = projetos[projetos["id"] == projeto_id]
        if not p.empty and float(p.iloc[0]["taxa_hora"]) > 0:
            return float(p.iloc[0]["taxa_hora"])
    if not membros.empty:
        m = membros[membros["id"] == membro_id]
        if not m.empty and float(m.iloc[0]["taxa_hora"]) > 0:
            return float(m.iloc[0]["taxa_hora"])
    return 0.0


# ==========================================================================
# Enriquecimento para relatórios
# ==========================================================================
def enriquecer(
    registos: pd.DataFrame,
    projetos: pd.DataFrame,
    tarefas: pd.DataFrame,
    membros: pd.DataFrame,
    clientes: pd.DataFrame,
    taxas: pd.DataFrame,
) -> pd.DataFrame:
    """Junta nomes, disciplina, cliente, taxas e custos a cada registo concluído."""
    colunas = [
        "id", "data", "membro_id", "membro", "equipa_id", "projeto_id", "codigo", "projeto",
        "cliente", "tarefa_id", "tarefa", "disciplina", "fase", "descricao", "tags",
        "hora_inicio", "hora_fim", "duracao_min", "horas", "faturavel", "taxa", "valor",
        "custo_hora", "custo", "origem", "sinalizado",
    ]
    if registos.empty:
        return pd.DataFrame(columns=colunas)

    df = registos[registos["estado"] != "Em curso"].copy()
    if df.empty:
        return pd.DataFrame(columns=colunas)

    proj = projetos.set_index("id") if not projetos.empty else pd.DataFrame()
    tar = tarefas.set_index("id") if not tarefas.empty else pd.DataFrame()
    memb = membros.set_index("id") if not membros.empty else pd.DataFrame()
    cli = dict(zip(clientes["id"], clientes["nome"])) if not clientes.empty else {}

    def _get(tabela, chave, coluna, omissao=""):
        if tabela.empty or chave not in tabela.index or coluna not in tabela.columns:
            return omissao
        v = tabela.at[chave, coluna]
        return omissao if v is None or (isinstance(v, float) and pd.isna(v)) else v

    df["membro"] = df["membro_id"].map(lambda i: _get(memb, i, "nome", i))
    df["equipa_id"] = df["membro_id"].map(lambda i: _get(memb, i, "equipa_id"))
    df["codigo"] = df["projeto_id"].map(lambda i: _get(proj, i, "codigo"))
    df["projeto"] = df["projeto_id"].map(lambda i: _get(proj, i, "nome", i))

    def _cliente(pid):
        cid = _get(proj, pid, "cliente_id")
        if cid and cid in cli:
            return cli[cid]
        return _get(proj, pid, "cliente") or "(sem cliente)"

    df["cliente"] = df["projeto_id"].map(_cliente)
    df["tarefa"] = df["tarefa_id"].map(lambda i: _get(tar, i, "nome", SEM_TAREFA) if i else SEM_TAREFA)
    df["disciplina"] = df["tarefa_id"].map(lambda i: _get(tar, i, "disciplina", "—") if i else "—")
    df["fase"] = df["tarefa_id"].map(lambda i: _get(tar, i, "fase", "—") if i else "—")

    df["duracao_min"] = pd.to_numeric(df["duracao_min"], errors="coerce").fillna(0)
    df["horas"] = df["duracao_min"] / 60.0
    df["faturavel"] = df["faturavel"].map(sim)

    cache_taxa: dict[tuple[str, str], float] = {}

    def _taxa(row):
        chave = (row["projeto_id"], row["membro_id"])
        if chave not in cache_taxa:
            cache_taxa[chave] = taxa_aplicavel(*chave, taxas, projetos, membros)
        return cache_taxa[chave]

    df["taxa"] = df.apply(_taxa, axis=1)
    df["valor"] = df["horas"] * df["taxa"] * df["faturavel"].astype(int)
    df["custo_hora"] = df["membro_id"].map(lambda i: float(_get(memb, i, "custo_hora", 0) or 0))
    df["custo"] = df["horas"] * df["custo_hora"]
    df["sinalizado"] = df["duracao_min"] > LIMITE_HORAS_REGISTO * 60

    return df[colunas].sort_values(["data", "membro", "hora_inicio"]).reset_index(drop=True)


# ==========================================================================
# Submissões e bloqueios
# ==========================================================================
def data_fecho(periodos: pd.DataFrame) -> date | None:
    """Data até à qual (inclusive) todos os registos estão bloqueados."""
    if periodos.empty:
        return None
    datas = periodos["data_fecho"].dropna()
    return None if datas.empty else datas.max().date()


def submissao(submissoes: pd.DataFrame, membro_id: str, seg: date) -> pd.Series | None:
    if submissoes.empty:
        return None
    alvo = pd.Timestamp(seg)
    s = submissoes[(submissoes["membro_id"] == membro_id) & (submissoes["semana"] == alvo)]
    if s.empty:
        return None
    return s.sort_values("atualizado_em").iloc[-1]


def estado_semana(submissoes: pd.DataFrame, membro_id: str, seg: date) -> str:
    """'' (aberta), 'Submetida', 'Aprovada' ou 'Devolvida'."""
    s = submissao(submissoes, membro_id, seg)
    return "" if s is None else str(s["estado"])


def motivo_bloqueio(
    d: date, membro_id: str, submissoes: pd.DataFrame, fecho: date | None
) -> str | None:
    """Motivo pelo qual a data não pode ser editada por este membro, ou None."""
    if d is None:
        return None
    if fecho and d <= fecho:
        return f"período fechado até {fecho:%d/%m/%Y}"
    estado = estado_semana(submissoes, membro_id, segunda(d))
    if estado == "Submetida":
        return "semana submetida para aprovação"
    if estado == "Aprovada":
        return "semana aprovada"
    return None


# ==========================================================================
# Grelha semanal
# ==========================================================================
@dataclass
class Plano:
    """Conjunto de escritas a aplicar, calculado antes de tocar na folha."""

    inserir: list[dict] = field(default_factory=list)
    atualizar: dict[str, dict] = field(default_factory=dict)
    eliminar: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)

    @property
    def vazio(self) -> bool:
        return not (self.inserir or self.atualizar or self.eliminar)


def grelha_atual(registos_semana: pd.DataFrame, seg: date) -> dict[tuple[str, str, date], int]:
    """Soma de minutos por (projeto, tarefa, dia) dos registos concluídos."""
    saida: dict[tuple[str, str, date], int] = {}
    if registos_semana.empty:
        return saida
    for _, r in registos_semana[registos_semana["estado"] != "Em curso"].iterrows():
        d = para_date(r["data"])
        if d is None or not (seg <= d <= seg + timedelta(days=6)):
            continue
        chave = (r["projeto_id"], r["tarefa_id"] or "", d)
        saida[chave] = saida.get(chave, 0) + int(r["duracao_min"] or 0)
    return saida


def plano_grelha(
    alvo: dict[tuple[str, str, date], int],
    registos_semana: pd.DataFrame,
    membro_id: str,
    seg: date,
    faturavel_projeto: dict[str, bool],
    bloqueio,  # callable(date) -> str | None
    rotulo,    # callable((pid, tid)) -> str
) -> Plano:
    """Traduz a grelha editada num plano de escritas.

    Regras por célula (projeto, tarefa, dia), com T = alvo e S = soma atual:
      T > S  acrescenta a diferença ao registo de grelha da célula, ou cria um;
      T < S  reduz primeiro os registos de grelha; se não chegar, a célula tem
             registos detalhados (temporizador/manual) e dá erro — esses
             editam-se na vista Lista, onde têm horas de início e fim.
    """
    plano = Plano()
    atual = grelha_atual(registos_semana, seg)
    concl = (
        registos_semana[registos_semana["estado"] != "Em curso"]
        if not registos_semana.empty else registos_semana
    )

    for chave in sorted(set(atual) | set(alvo), key=lambda c: (c[0], c[1], c[2])):
        pid, tid, d = chave
        t = arredondar(alvo.get(chave, 0), minimo=False)
        s = atual.get(chave, 0)
        if t == s:
            continue

        motivo = bloqueio(d)
        if motivo:
            plano.erros.append(f"{rotulo((pid, tid))}, {d:%d/%m}: {motivo}.")
            continue

        celula = concl[
            (concl["projeto_id"] == pid)
            & (concl["tarefa_id"].fillna("") == tid)
            & (concl["data"].map(para_date) == d)
        ] if not concl.empty else concl
        grelha = celula[celula["origem"] == "grelha"] if not celula.empty else celula

        if t > s:
            dif = t - s
            if not grelha.empty:
                g = grelha.iloc[0]
                plano.atualizar[g["id"]] = {"duracao_min": int(g["duracao_min"]) + dif}
            else:
                plano.inserir.append({
                    "membro_id": membro_id,
                    "projeto_id": pid,
                    "tarefa_id": tid,
                    "data": d,
                    "hora_inicio": "",
                    "hora_fim": "",
                    "duracao_min": dif,
                    "descricao": "",
                    "tags": "",
                    "faturavel": "Sim" if faturavel_projeto.get(pid, True) else "Não",
                    "estado": "Concluído",
                    "inicio_ts": "",
                    "origem": "grelha",
                })
        else:
            falta = s - t
            for _, g in grelha.iterrows():
                if falta <= 0:
                    break
                dur = int(g["duracao_min"])
                tirar = min(dur, falta)
                if dur - tirar == 0:
                    plano.eliminar.append(g["id"])
                else:
                    plano.atualizar[g["id"]] = {"duracao_min": dur - tirar}
                falta -= tirar
            if falta > 0:
                plano.erros.append(
                    f"{rotulo((pid, tid))}, {d:%d/%m}: não é possível reduzir "
                    f"{fmt_horas(falta)} porque a célula tem registos detalhados. "
                    "Edita-os na vista Lista."
                )
                # Anula as escritas parciais desta célula para não deixar meio-termo
                for _, g in grelha.iterrows():
                    plano.atualizar.pop(g["id"], None)
                    if g["id"] in plano.eliminar:
                        plano.eliminar.remove(g["id"])

    return plano


# ==========================================================================
# Vista Lista (registos detalhados)
# ==========================================================================
def duracao_linha(hora_inicio, hora_fim, horas) -> tuple[int, str, str]:
    """Duração em minutos a partir de início/fim, ou das horas indicadas.

    Devolve (minutos, hora_inicio 'HH:MM' ou '', hora_fim 'HH:MM' ou '').
    Com início e duração mas sem fim, o fim é calculado.
    """
    hi, hf = para_time(hora_inicio), para_time(hora_fim)
    if hi and hf:
        return arredondar(minutos_entre(hi, hf)), hi.strftime("%H:%M"), hf.strftime("%H:%M")
    try:
        h = float(horas) if horas not in (None, "") and not pd.isna(horas) else 0.0
    except (TypeError, ValueError):
        h = 0.0
    minutos = arredondar(h * 60)
    if hi and minutos:
        fim = (datetime.combine(date(2000, 1, 1), hi) + timedelta(minutes=minutos)).time()
        return minutos, hi.strftime("%H:%M"), fim.strftime("%H:%M")
    return minutos, (hi.strftime("%H:%M") if hi else ""), ""


def _vazio(v) -> bool:
    if v is None or v == "" or v is pd.NaT:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _mesmo_valor(a, b) -> bool:
    try:
        return abs(float(a or 0) - float(b or 0)) < 1e-6
    except (TypeError, ValueError):
        return str(a) == str(b)


def plano_lista(
    original: pd.DataFrame,
    editado: pd.DataFrame,
    membro_id: str,
    por_rotulo: dict[str, tuple[str, str]],
    bloqueio,  # callable(date) -> str | None
    faturavel_projeto: dict[str, bool] | None = None,
) -> Plano:
    """Compara a tabela original com a editada e devolve o plano de escritas.

    As duas tabelas têm as colunas: id, data, atividade, hora_inicio, hora_fim,
    horas, descricao, tags, faturavel. A original tem também duracao_min.
    Se início, fim e horas não mudaram, a duração gravada mantém-se (evita
    que um temporizador de 58 min passe a outro valor só por editar a descrição).
    """
    faturavel_projeto = faturavel_projeto or {}
    plano = Plano()
    orig = {r["id"]: r for _, r in original.iterrows() if r["id"]}
    presentes = (
        set(editado["id"].dropna().astype(str)) if not editado.empty and "id" in editado else set()
    )

    for n, (_, r) in enumerate(editado.iterrows(), start=1):
        rid = r.get("id")
        rid = "" if rid is None or (isinstance(rid, float) and pd.isna(rid)) else str(rid)
        d = para_date(r.get("data"))
        ativ = r.get("atividade")
        vazia = d is None and _vazio(ativ) and _vazio(r.get("horas")) and _vazio(r.get("hora_inicio"))
        if vazia and not rid:
            continue  # linha em branco acrescentada por engano

        ref = f"Linha {n}"
        if d is None:
            plano.erros.append(f"{ref}: falta a data.")
            continue
        if _vazio(ativ) or ativ not in por_rotulo:
            plano.erros.append(f"{ref}: escolhe a atividade (projeto · tarefa).")
            continue
        minutos, hi, hf = duracao_linha(r.get("hora_inicio"), r.get("hora_fim"), r.get("horas"))
        if rid and rid in orig:
            o = orig[rid]
            if (
                para_time(r.get("hora_inicio")) == para_time(o.get("hora_inicio"))
                and para_time(r.get("hora_fim")) == para_time(o.get("hora_fim"))
                and _mesmo_valor(r.get("horas"), o.get("horas"))
            ):
                minutos = int(o.get("duracao_min") or 0)
                hi = str(o.get("hora_inicio") or "") if not isinstance(o.get("hora_inicio"), time) \
                    else o["hora_inicio"].strftime("%H:%M")
                hf = str(o.get("hora_fim") or "") if not isinstance(o.get("hora_fim"), time) \
                    else o["hora_fim"].strftime("%H:%M")
        if minutos <= 0:
            plano.erros.append(f"{ref}: indica as horas de início e fim, ou a duração.")
            continue

        pid, tid = por_rotulo[ativ]
        fat = r.get("faturavel")
        if fat is None or (isinstance(fat, float) and pd.isna(fat)):
            fat = faturavel_projeto.get(pid, True)
        campos = {
            "membro_id": membro_id,
            "projeto_id": pid,
            "tarefa_id": tid,
            "data": d,
            "hora_inicio": hi,
            "hora_fim": hf,
            "duracao_min": minutos,
            "descricao": str(r.get("descricao") or "").strip(),
            "tags": tags_texto(tags_lista(r.get("tags"))),
            "faturavel": "Sim" if sim(fat) else "Não",
        }

        if rid and rid in orig:
            o = orig[rid]
            o_hi = para_time(o.get("hora_inicio"))
            o_hf = para_time(o.get("hora_fim"))
            antes = {
                "projeto_id": por_rotulo.get(o["atividade"], ("", ""))[0],
                "tarefa_id": por_rotulo.get(o["atividade"], ("", ""))[1],
                "data": para_date(o["data"]),
                "hora_inicio": o_hi.strftime("%H:%M") if o_hi else "",
                "hora_fim": o_hf.strftime("%H:%M") if o_hf else "",
                "duracao_min": int(o.get("duracao_min") or 0),
                "descricao": str(o.get("descricao") or "").strip(),
                "tags": tags_texto(tags_lista(o.get("tags"))),
                "faturavel": "Sim" if sim(o.get("faturavel")) else "Não",
            }
            alterado = {k: v for k, v in campos.items() if k != "membro_id" and antes.get(k) != v}
            if not alterado:
                continue
            for dia in {antes["data"], d}:
                motivo = bloqueio(dia)
                if motivo:
                    plano.erros.append(f"{ref} ({dia:%d/%m}): {motivo}.")
                    break
            else:
                plano.atualizar[rid] = alterado
        else:
            motivo = bloqueio(d)
            if motivo:
                plano.erros.append(f"{ref} ({d:%d/%m}): {motivo}.")
                continue
            plano.inserir.append({**campos, "estado": "Concluído", "inicio_ts": "", "origem": "manual"})

    for rid, o in orig.items():
        if rid in presentes:
            continue
        d = para_date(o["data"])
        motivo = bloqueio(d)
        if motivo:
            plano.erros.append(f"Registo de {d:%d/%m} não pode ser eliminado: {motivo}.")
        else:
            plano.eliminar.append(rid)

    return plano


# ==========================================================================
# Orçamento
# ==========================================================================
def nivel_alerta(consumo: float) -> str:
    aviso, excedido = ALERTA_ORCAMENTO
    if consumo >= excedido:
        return "Excedido"
    if consumo >= aviso:
        return "Atenção"
    return "OK"


def orcamento_projetos(enriq: pd.DataFrame, projetos: pd.DataFrame) -> pd.DataFrame:
    """Horas orçadas vs. registadas por projeto (todos os registos, sem filtro de datas)."""
    if projetos.empty:
        return pd.DataFrame(columns=["projeto_id", "codigo", "projeto", "orcadas", "registadas",
                                     "consumo", "alerta"])
    reg = enriq.groupby("projeto_id")["horas"].sum() if not enriq.empty else pd.Series(dtype=float)
    df = projetos[["id", "codigo", "nome", "horas_orcadas"]].rename(
        columns={"id": "projeto_id", "nome": "projeto", "horas_orcadas": "orcadas"}
    )
    df["registadas"] = df["projeto_id"].map(reg).fillna(0.0)
    df = df[(df["orcadas"] > 0) | (df["registadas"] > 0)].copy()
    df["consumo"] = df.apply(
        lambda r: r["registadas"] / r["orcadas"] if r["orcadas"] > 0 else float("nan"), axis=1
    )
    df["alerta"] = df["consumo"].map(lambda c: "Sem orçamento" if pd.isna(c) else nivel_alerta(c))
    return df.sort_values("consumo", ascending=False, na_position="last").reset_index(drop=True)


def orcamento_tarefas(enriq: pd.DataFrame, tarefas: pd.DataFrame, projetos: pd.DataFrame) -> pd.DataFrame:
    colunas = ["tarefa_id", "projeto", "tarefa", "disciplina", "orcadas", "registadas",
               "consumo", "alerta"]
    if tarefas.empty:
        return pd.DataFrame(columns=colunas)
    reg = enriq.groupby("tarefa_id")["horas"].sum() if not enriq.empty else pd.Series(dtype=float)
    nomes = dict(zip(projetos["id"], projetos["codigo"].where(projetos["codigo"] != "", projetos["nome"]))) \
        if not projetos.empty else {}
    df = tarefas[tarefas["horas_orcadas"] > 0][["id", "projeto_id", "nome", "disciplina", "horas_orcadas"]].copy()
    if df.empty:
        return pd.DataFrame(columns=colunas)
    df = df.rename(columns={"id": "tarefa_id", "nome": "tarefa", "horas_orcadas": "orcadas"})
    df["projeto"] = df["projeto_id"].map(nomes)
    df["registadas"] = df["tarefa_id"].map(reg).fillna(0.0)
    df["consumo"] = df["registadas"] / df["orcadas"]
    df["alerta"] = df["consumo"].map(nivel_alerta)
    return df[colunas].sort_values("consumo", ascending=False).reset_index(drop=True)


# ==========================================================================
# Painel pessoal
# ==========================================================================
def resumo_semana(
    registos: pd.DataFrame, membro_id: str, seg: date, hoje: date, horas_semana: float
) -> dict:
    """Totais da semana e dias úteis já passados abaixo da meta diária."""
    meta_sem = float(horas_semana or HORAS_SEMANA_OMISSAO)
    meta_dia = meta_sem / 5.0
    dias = dias_da_semana(seg)
    por_dia = {d: 0 for d in dias}
    if not registos.empty:
        dele = registos[(registos["membro_id"] == membro_id) & (registos["estado"] != "Em curso")]
        for _, r in dele.iterrows():
            d = para_date(r["data"])
            if d in por_dia:
                por_dia[d] += int(r["duracao_min"] or 0)
    total = sum(por_dia.values())
    em_falta = [d for d in dias[:5] if d <= hoje and por_dia[d] < meta_dia * 60]
    return {
        "por_dia": por_dia,
        "total_min": total,
        "meta_min": int(meta_sem * 60),
        "dias_em_falta": em_falta,
    }
