"""Registo de horas: temporizador, grelha semanal, lista detalhada e submissão."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from lib import data, sessao
from lib import horas as H
from lib.config import (
    APP_ICON,
    DIAS_SEMANA,
    LIMITE_HORAS_REGISTO,
    TAGS_SUGERIDAS,
)

st.set_page_config(page_title="Registo de Horas", page_icon=APP_ICON, layout="wide")

if not data.ligacao_ativa():
    st.error("Sem ligação ao Google Sheets. Configura os secrets na página inicial.")
    st.stop()

# --------------------------------------------------------------------------
# Dados
# --------------------------------------------------------------------------
membros = data.ler("membros")
projetos = data.ler("projetos")
tarefas = data.ler("tarefas")
registos = data.ler("registos")
submissoes = data.ler("submissoes")
periodos = data.ler("periodos_fechados")
clientes = data.ler("clientes")
taxas = data.ler("taxas")

u = sessao.exigir_utilizador(membros)
sessao.cartao_lateral(u)
email = data.utilizador_atual()
hoje = data.hoje()
fecho = H.data_fecho(periodos)

st.title("Registo de horas")

if projetos.empty:
    st.warning("Ainda não há projetos. Cria um em **Projetos** para começar a registar horas.", icon="📁")
    st.stop()

faturavel_proj = {
    r["id"]: (H.sim(r["faturavel"]) if str(r["faturavel"]).strip() else True)
    for _, r in projetos.iterrows()
}

# --------------------------------------------------------------------------
# Membro em edição (gestor/admin podem editar horas de outros)
# --------------------------------------------------------------------------
visiveis = sessao.membros_visiveis(u, membros)
alvo_id = u.id
if u.gestor and len(visiveis) > 1:
    nomes_vis = dict(zip(visiveis["id"], visiveis["nome"]))
    ids = list(nomes_vis.keys())
    alvo_id = st.selectbox(
        "Horas de", ids, index=ids.index(u.id) if u.id in ids else 0,
        format_func=lambda i: nomes_vis[i] + (" (eu)" if i == u.id else ""),
        help="Como gestor/admin podes consultar e corrigir as horas da equipa.",
    )
alvo = membros[membros["id"] == alvo_id].iloc[0]
proprio = alvo_id == u.id
horas_semana_alvo = float(alvo["horas_semana"] or 0) or 40.0

meus = registos[registos["membro_id"] == alvo_id] if not registos.empty else registos


def bloqueio(d):
    return H.motivo_bloqueio(d, alvo_id, submissoes, fecho)


# Orçamento consumido (todos os registos), para avisos ao escolher atividade
enriq_todos = H.enriquecer(registos, projetos, tarefas, membros, clientes, taxas)
orc_p = H.orcamento_projetos(enriq_todos, projetos).set_index("projeto_id")
orc_t = H.orcamento_tarefas(enriq_todos, tarefas, projetos).set_index("tarefa_id")


def aviso_orcamento(pid: str, tid: str) -> None:
    for tabela, chave, nome in ((orc_t, tid, "tarefa"), (orc_p, pid, "projeto")):
        if chave and chave in tabela.index:
            linha = tabela.loc[chave]
            if linha["alerta"] in ("Atenção", "Excedido"):
                st.warning(
                    f"Orçamento da {nome}: {linha['registadas']:.1f} h de "
                    f"{linha['orcadas']:.1f} h ({linha['consumo']:.0%}).",
                    icon="⚠️" if linha["alerta"] == "Atenção" else "🛑",
                )


def aplicar(plano: H.Plano, chave_editor: str | None = None) -> None:
    """Grava um plano em lote (máximo três chamadas à API)."""
    if plano.erros:
        for e in plano.erros:
            st.error(e)
        st.info("Nada foi gravado. Corrige os pontos acima e volta a guardar.")
        return
    if plano.vazio:
        st.info("Sem alterações para gravar.")
        return
    with st.spinner("A gravar..."):
        data.inserir_lote("registos", plano.inserir, utilizador=email)
        data.atualizar_lote("registos", plano.atualizar, utilizador=email)
        data.eliminar_lote("registos", plano.eliminar)
    if chave_editor:
        st.session_state.pop(chave_editor, None)
    st.toast(
        f"Gravado: {len(plano.inserir)} novo(s), {len(plano.atualizar)} alterado(s), "
        f"{len(plano.eliminar)} removido(s).", icon="✅",
    )
    st.rerun()


# ==========================================================================
# Temporizador (só para as próprias horas)
# ==========================================================================
por_rotulo_ativos, por_chave_ativos = H.rotulos_atividade(projetos, tarefas)
em_curso = meus[meus["estado"] == "Em curso"] if not meus.empty else meus

if proprio:
    st.subheader("⏱️ Temporizador")
    if not em_curso.empty:
        t = em_curso.iloc[0]
        try:
            inicio_ts = datetime.strptime(str(t["inicio_ts"]), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            inicio_ts = data.agora()
        _, por_chave_t = H.rotulos_atividade(
            projetos, tarefas, incluir_ids={(t["projeto_id"], t["tarefa_id"])}, so_ativos=False
        )
        rotulo_t = por_chave_t.get((t["projeto_id"], t["tarefa_id"]), t["projeto_id"])

        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            st.markdown(f"**{rotulo_t}**")
            if t["descricao"]:
                st.caption(t["descricao"])
            st.caption(f"Iniciado às {inicio_ts:%H:%M} de {inicio_ts:%d/%m/%Y}")

        @st.fragment(run_every=timedelta(seconds=30))
        def contador():
            decorrido = (data.agora() - inicio_ts).total_seconds() / 60
            st.metric("Decorrido", H.fmt_horas(decorrido))
            if decorrido > LIMITE_HORAS_REGISTO * 60:
                st.warning(f"Mais de {LIMITE_HORAS_REGISTO} h — esqueceste-te de parar?", icon="⏰")

        with c2:
            contador()
        with c3:
            if st.button("⏹️ Parar", type="primary", width="stretch"):
                d = inicio_ts.date()
                motivo = bloqueio(d)
                if motivo:
                    st.error(f"Não é possível gravar em {d:%d/%m}: {motivo}. Descarta o temporizador.")
                else:
                    fim = data.agora()
                    minutos = H.arredondar((fim - inicio_ts).total_seconds() / 60)
                    data.atualizar(
                        "registos", t["id"],
                        {
                            "hora_fim": fim.strftime("%H:%M"),
                            "duracao_min": minutos,
                            "estado": "Concluído",
                        },
                        utilizador=email,
                    )
                    st.toast(f"Registadas {H.fmt_horas(minutos)} h.", icon="✅")
                    st.rerun()
            if st.button("🗑️ Descartar", width="stretch"):
                data.eliminar("registos", t["id"])
                st.rerun()
    else:
        if not por_rotulo_ativos:
            st.caption("Não há projetos ativos.")
        else:
            c1, c2 = st.columns([2, 3])
            ativ = c1.selectbox("Atividade", list(por_rotulo_ativos.keys()), key="tmp_ativ")
            desc = c2.text_input("Descrição", key="tmp_desc", placeholder="O que estás a fazer?")
            pid, tid = por_rotulo_ativos[ativ]
            tags_usadas = sorted(
                {t for x in registos["tags"] for t in H.tags_lista(x)} if not registos.empty else set()
            )
            c3, c4, c5 = st.columns([3, 1, 1])
            tags_sel = c3.multiselect(
                "Tags", sorted(set(TAGS_SUGERIDAS) | set(tags_usadas)), key="tmp_tags",
                accept_new_options=True,
            )
            fat = c4.checkbox("Faturável", value=faturavel_proj.get(pid, True), key=f"tmp_fat_{pid}")
            aviso_orcamento(pid, tid)
            c5.write("")
            if c5.button("▶️ Iniciar", type="primary", width="stretch"):
                if bloqueio(hoje):
                    st.error(f"Hoje não é editável: {bloqueio(hoje)}.")
                else:
                    agora = data.agora()
                    data.inserir(
                        "registos",
                        {
                            "membro_id": u.id,
                            "projeto_id": pid,
                            "tarefa_id": tid,
                            "data": agora.date(),
                            "hora_inicio": agora.strftime("%H:%M"),
                            "hora_fim": "",
                            "duracao_min": 0,
                            "descricao": desc.strip(),
                            "tags": H.tags_texto(tags_sel),
                            "faturavel": "Sim" if fat else "Não",
                            "estado": "Em curso",
                            "inicio_ts": agora.strftime("%Y-%m-%d %H:%M:%S"),
                            "origem": "temporizador",
                        },
                        utilizador=email,
                    )
                    for k in ("tmp_desc", "tmp_tags"):
                        st.session_state.pop(k, None)
                    st.rerun()
    st.divider()
elif not em_curso.empty:
    st.info(f"{alvo['nome']} tem um temporizador a correr desde {em_curso.iloc[0]['hora_inicio']}.", icon="⏱️")

# ==========================================================================
# Navegação por semana
# ==========================================================================
if "semana" not in st.session_state:
    st.session_state.semana = H.segunda(hoje)

n1, n2, n3, n4 = st.columns([1, 2, 1, 1])
if n1.button("◀ Anterior", width="stretch"):
    st.session_state.semana -= timedelta(days=7)
    st.rerun()
escolhida = n2.date_input(
    "Semana", value=st.session_state.semana, format="DD/MM/YYYY", label_visibility="collapsed"
)
if H.segunda(escolhida) != st.session_state.semana:
    st.session_state.semana = H.segunda(escolhida)
    st.rerun()
if n3.button("Seguinte ▶", width="stretch"):
    st.session_state.semana += timedelta(days=7)
    st.rerun()
if n4.button("Esta semana", width="stretch"):
    st.session_state.semana = H.segunda(hoje)
    st.rerun()

seg = st.session_state.semana
dias = H.dias_da_semana(seg)
st.markdown(f"#### Semana de {dias[0]:%d/%m} a {dias[-1]:%d/%m/%Y}")

semana_regs = (
    meus[(meus["data"] >= pd.Timestamp(dias[0])) & (meus["data"] <= pd.Timestamp(dias[-1]))]
    if not meus.empty else meus
)
concluidos = semana_regs[semana_regs["estado"] != "Em curso"] if not semana_regs.empty else semana_regs

# --------------------------------------------------------------------------
# Estado da semana e submissão
# --------------------------------------------------------------------------
estado = H.estado_semana(submissoes, alvo_id, seg)
sub = H.submissao(submissoes, alvo_id, seg)
resumo = H.resumo_semana(registos, alvo_id, seg, hoje, horas_semana_alvo)
semana_fechada = fecho is not None and dias[-1] <= fecho
bloqueada = estado in ("Submetida", "Aprovada") or semana_fechada

m1, m2, m3 = st.columns(3)
m1.metric("Total da semana", H.fmt_horas(resumo["total_min"]), help="horas:minutos")
m2.metric("Meta", H.fmt_horas(resumo["meta_min"]))
m3.metric("Estado", estado or ("Fechada" if semana_fechada else "Aberta"))

if semana_fechada:
    st.info(f"Período fechado até {fecho:%d/%m/%Y}. Só um administrador pode reabrir.", icon="🔒")
elif estado == "Aprovada":
    st.success(
        f"Semana aprovada por {sub['revisto_por']} em {sub['revisto_em']}. "
        "Para corrigir, pede ao gestor para a reabrir.", icon="✅",
    )
elif estado == "Submetida":
    st.info(f"Submetida em {sub['submetido_em']}, a aguardar aprovação.", icon="📨")
    if st.button("Retirar submissão"):
        data.eliminar("submissoes", sub["id"])
        st.rerun()
else:
    if estado == "Devolvida":
        st.warning(
            f"Devolvida por {sub['revisto_por']}: «{sub['comentario'] or 'sem comentário'}». "
            "Corrige e volta a submeter.", icon="↩️",
        )
    if resumo["dias_em_falta"]:
        st.caption(
            "Dias úteis abaixo da meta diária: "
            + ", ".join(f"{DIAS_SEMANA[d.weekday()]} {d:%d/%m}" for d in resumo["dias_em_falta"])
        )
    timer_na_semana = not semana_regs.empty and (semana_regs["estado"] == "Em curso").any()
    if st.button("📨 Submeter semana para aprovação", type="primary"):
        if timer_na_semana:
            st.error("Há um temporizador a correr nesta semana. Para-o antes de submeter.")
        elif resumo["total_min"] == 0:
            st.error("A semana não tem horas registadas.")
        else:
            campos = {
                "membro_id": alvo_id,
                "semana": seg,
                "estado": "Submetida",
                "submetido_em": data.agora().strftime("%Y-%m-%d %H:%M"),
                "revisto_por": "",
                "revisto_em": "",
                "comentario": "",
            }
            if sub is not None:
                data.atualizar("submissoes", sub["id"], campos, utilizador=email)
            else:
                data.inserir("submissoes", campos, utilizador=email)
            st.rerun()

# ==========================================================================
# Separadores
# ==========================================================================
incluir = set(zip(concluidos["projeto_id"], concluidos["tarefa_id"].fillna(""))) \
    if not concluidos.empty else set()
por_rotulo, por_chave = H.rotulos_atividade(projetos, tarefas, incluir_ids=incluir)
rotulo = lambda chave: por_chave.get(chave, f"{chave[0]} · {chave[1]}")  # noqa: E731
col_dias = [f"{DIAS_SEMANA[i]} {d:%d/%m}" for i, d in enumerate(dias)]

aba_grelha, aba_lista, aba_resumo = st.tabs(["Grelha semanal", "Lista", "Resumo da semana"])

# --------------------------------------------------------------------------
# Grelha semanal
# --------------------------------------------------------------------------
with aba_grelha:
    atual = H.grelha_atual(concluidos, seg)
    linhas: dict[str, dict] = {}
    for (pid, tid, d), minutos in atual.items():
        r = rotulo((pid, tid))
        linhas.setdefault(r, {"Atividade": r, **{c: 0.0 for c in col_dias}})
        linhas[r][col_dias[(d - seg).days]] += minutos / 60
    grelha = pd.DataFrame(list(linhas.values()), columns=["Atividade"] + col_dias)
    grelha = grelha.sort_values("Atividade").reset_index(drop=True)

    st.caption(
        "Horas decimais (1,5 = 1h30), arredondadas a 15 min ao gravar. Acrescenta linhas "
        "no fim da tabela. Células com registos do temporizador só podem ser reduzidas na vista Lista."
    )
    chave_grelha = f"grelha_{alvo_id}_{seg}"
    editada = st.data_editor(
        grelha,
        key=chave_grelha,
        num_rows="fixed" if bloqueada else "dynamic",
        disabled=bloqueada,
        hide_index=True,
        width="stretch",
        column_config={
            "Atividade": st.column_config.SelectboxColumn(
                "Atividade", options=list(por_rotulo.keys()), required=True, width="large"
            ),
            **{
                c: st.column_config.NumberColumn(c, min_value=0.0, max_value=24.0, step=0.25, format="%.2f")
                for c in col_dias
            },
        },
    )

    totais = editada[col_dias].apply(pd.to_numeric, errors="coerce").fillna(0).sum()
    st.dataframe(
        pd.DataFrame([["Total", *totais.tolist(), totais.sum()]], columns=["", *col_dias, "Semana"]),
        hide_index=True, width="stretch",
        column_config={c: st.column_config.NumberColumn(format="%.2f") for c in [*col_dias, "Semana"]},
    )

    if not bloqueada and st.button("💾 Guardar grelha", type="primary"):
        alvo_min: dict[tuple, int] = {}
        erros = []
        for _, r in editada.iterrows():
            a = r["Atividade"]
            if not a or (isinstance(a, float) and pd.isna(a)):
                if any(pd.to_numeric(r[c], errors="coerce") > 0 for c in col_dias):
                    erros.append("Há uma linha com horas mas sem atividade.")
                continue
            pid, tid = por_rotulo[a]
            for i, c in enumerate(col_dias):
                v = pd.to_numeric(r[c], errors="coerce")
                if pd.notna(v) and v > 0:
                    k = (pid, tid, dias[i])
                    alvo_min[k] = alvo_min.get(k, 0) + int(round(v * 60))
        if erros:
            for e in erros:
                st.error(e)
        else:
            plano = H.plano_grelha(alvo_min, concluidos, alvo_id, seg, faturavel_proj, bloqueio, rotulo)
            aplicar(plano, chave_grelha)

# --------------------------------------------------------------------------
# Lista detalhada
# --------------------------------------------------------------------------
with aba_lista:
    if concluidos.empty:
        lista = pd.DataFrame(columns=["id", "data", "atividade", "hora_inicio", "hora_fim", "horas",
                                      "descricao", "tags", "faturavel", "origem", "duracao_min"])
    else:
        c = concluidos.sort_values(["data", "hora_inicio"])
        lista = pd.DataFrame({
            "id": c["id"],
            "data": c["data"].dt.date,
            "atividade": [rotulo((p, t or "")) for p, t in zip(c["projeto_id"], c["tarefa_id"])],
            "hora_inicio": c["hora_inicio"].map(H.para_time),
            "hora_fim": c["hora_fim"].map(H.para_time),
            "horas": c["duracao_min"] / 60,
            "descricao": c["descricao"],
            "tags": c["tags"],
            "faturavel": c["faturavel"].map(H.sim),
            "origem": c["origem"],
            "duracao_min": c["duracao_min"],
        }).reset_index(drop=True)
    lista["⚠️"] = lista["horas"].astype(float) > LIMITE_HORAS_REGISTO

    st.caption(
        "Com início e fim preenchidos, a duração é calculada a partir deles; com início e "
        "duração, o fim é calculado. ⚠️ assinala registos com mais de "
        f"{LIMITE_HORAS_REGISTO} h. Para apagar, seleciona a linha e usa o caixote."
    )
    chave_lista = f"lista_{alvo_id}_{seg}"
    editada_l = st.data_editor(
        lista,
        key=chave_lista,
        num_rows="fixed" if bloqueada else "dynamic",
        disabled=True if bloqueada else ["origem", "⚠️"],
        hide_index=True,
        width="stretch",
        column_order=["⚠️", "data", "atividade", "hora_inicio", "hora_fim", "horas",
                      "descricao", "tags", "faturavel", "origem"],
        column_config={
            "⚠️": st.column_config.CheckboxColumn("⚠️", width="small"),
            "data": st.column_config.DateColumn(
                "Data", format="DD/MM/YYYY", min_value=dias[0], max_value=dias[-1], required=True
            ),
            "atividade": st.column_config.SelectboxColumn(
                "Atividade", options=list(por_rotulo.keys()), required=True, width="large"
            ),
            "hora_inicio": st.column_config.TimeColumn("Início", format="HH:mm", step=60 * 15),
            "hora_fim": st.column_config.TimeColumn("Fim", format="HH:mm", step=60 * 15),
            "horas": st.column_config.NumberColumn("Horas", min_value=0.0, max_value=24.0,
                                                   step=0.25, format="%.2f"),
            "descricao": st.column_config.TextColumn("Descrição", width="large"),
            "tags": st.column_config.TextColumn("Tags", help="Separadas por vírgula"),
            "faturavel": st.column_config.CheckboxColumn("Faturável"),
            "origem": st.column_config.TextColumn("Origem"),
        },
    )

    if not bloqueada and st.button("💾 Guardar lista", type="primary"):
        plano = H.plano_lista(lista, editada_l, alvo_id, por_rotulo, bloqueio, faturavel_proj)
        aplicar(plano, chave_lista)

# --------------------------------------------------------------------------
# Resumo da semana
# --------------------------------------------------------------------------
with aba_resumo:
    if concluidos.empty:
        st.caption("Sem registos nesta semana.")
    else:
        e = H.enriquecer(concluidos, projetos, tarefas, membros, clientes, taxas)
        esq, dir_ = st.columns(2)
        with esq:
            st.markdown("**Por projeto**")
            st.dataframe(
                e.groupby(["codigo", "projeto"], as_index=False)["horas"].sum()
                 .sort_values("horas", ascending=False),
                hide_index=True, width="stretch",
                column_config={"codigo": "Código", "projeto": "Projeto",
                               "horas": st.column_config.NumberColumn("Horas", format="%.2f")},
            )
        with dir_:
            st.markdown("**Por disciplina**")
            st.dataframe(
                e.groupby("disciplina", as_index=False)["horas"].sum()
                 .sort_values("horas", ascending=False),
                hide_index=True, width="stretch",
                column_config={"disciplina": "Disciplina",
                               "horas": st.column_config.NumberColumn("Horas", format="%.2f")},
            )
        por_dia = pd.DataFrame({
            "Dia": col_dias,
            "Horas": [resumo["por_dia"][d] / 60 for d in dias],
        })
        st.bar_chart(por_dia, x="Dia", y="Horas", height=220)
        fat_h = e.loc[e["faturavel"], "horas"].sum()
        st.caption(f"Faturável: {fat_h:.2f} h de {e['horas'].sum():.2f} h.")
