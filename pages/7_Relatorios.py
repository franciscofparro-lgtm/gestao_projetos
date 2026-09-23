"""Relatórios de horas: resumo, detalhado, semanal e orçamento, com exportação."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from lib import data, sessao
from lib import exportar as X
from lib import horas as H
from lib.config import APP_ICON, DISCIPLINAS_KEYS, rotulo_disciplina

st.set_page_config(page_title="Relatórios", page_icon=APP_ICON, layout="wide")

if not data.ligacao_ativa():
    st.error("Sem ligação ao Google Sheets. Configura os secrets na página inicial.")
    st.stop()

membros = data.ler("membros")
u = sessao.exigir_utilizador(membros)
sessao.cartao_lateral(u)

projetos = data.ler("projetos")
tarefas = data.ler("tarefas")
registos = data.ler("registos")
clientes = data.ler("clientes")
taxas = data.ler("taxas")
hoje = data.hoje()

st.title("Relatórios")

visiveis = sessao.membros_visiveis(u, membros)
todos = H.enriquecer(registos, projetos, tarefas, membros, clientes, taxas)
base = todos[todos["membro_id"].isin(set(visiveis["id"]))] if not todos.empty else todos

if not u.gestor:
    st.caption("Estás a ver apenas as tuas horas.")
elif not u.admin:
    st.caption("Estás a ver as horas da tua equipa.")

# ==========================================================================
# Filtros
# ==========================================================================
def _periodo(nome: str) -> tuple[date, date]:
    seg = H.segunda(hoje)
    ini_mes = hoje.replace(day=1)
    fim_mes_ant = ini_mes - timedelta(days=1)
    return {
        "Esta semana": (seg, seg + timedelta(days=6)),
        "Semana passada": (seg - timedelta(days=7), seg - timedelta(days=1)),
        "Este mês": (ini_mes, (ini_mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)),
        "Mês passado": (fim_mes_ant.replace(day=1), fim_mes_ant),
        "Últimos 30 dias": (hoje - timedelta(days=29), hoje),
        "Este ano": (date(hoje.year, 1, 1), date(hoje.year, 12, 31)),
        "Ano passado": (date(hoje.year - 1, 1, 1), date(hoje.year - 1, 12, 31)),
    }.get(nome, (ini_mes, hoje))


with st.container(border=True):
    f1, f2, f3 = st.columns([1, 1, 1])
    preset = f1.selectbox(
        "Período",
        ["Este mês", "Mês passado", "Esta semana", "Semana passada", "Últimos 30 dias",
         "Este ano", "Ano passado", "Personalizado"],
    )
    ini_p, fim_p = _periodo(preset)
    if preset == "Personalizado":
        ini = f2.date_input("De", value=hoje.replace(day=1), format="DD/MM/YYYY")
        fim = f3.date_input("Até", value=hoje, format="DD/MM/YYYY")
    else:
        ini, fim = ini_p, fim_p
        f2.date_input("De", value=ini, format="DD/MM/YYYY", disabled=True)
        f3.date_input("Até", value=fim, format="DD/MM/YYYY", disabled=True)

    g1, g2, g3 = st.columns(3)
    nomes_proj = {r["id"]: (r["codigo"] or r["nome"]) for _, r in projetos.iterrows()} if not projetos.empty else {}
    sel_proj = g1.multiselect("Projetos", list(nomes_proj), format_func=lambda i: nomes_proj[i],
                              placeholder="Todos")
    lista_cli = sorted(base["cliente"].dropna().unique().tolist()) if not base.empty else []
    sel_cli = g2.multiselect("Clientes", lista_cli, placeholder="Todos")
    sel_disc = g3.multiselect("Disciplinas", DISCIPLINAS_KEYS + ["—"],
                              format_func=lambda d: "Sem disciplina" if d == "—" else rotulo_disciplina(d),
                              placeholder="Todas")

    h1, h2, h3 = st.columns(3)
    nomes_vis = dict(zip(visiveis["id"], visiveis["nome"])) if not visiveis.empty else {}
    sel_memb = h1.multiselect("Membros", list(nomes_vis), format_func=lambda i: nomes_vis[i],
                              placeholder="Todos", disabled=len(nomes_vis) <= 1)
    todas_tags = sorted({t for x in base["tags"] for t in H.tags_lista(x)}) if not base.empty else []
    sel_tags = h2.multiselect("Tags (qualquer uma)", todas_tags, placeholder="Todas")
    sel_fat = h3.selectbox("Faturação", ["Todos", "Faturável", "Não faturável"])

if ini > fim:
    st.error("A data inicial é posterior à final.")
    st.stop()

df = base.copy()
if not df.empty:
    df = df[(df["data"] >= pd.Timestamp(ini)) & (df["data"] <= pd.Timestamp(fim))]
    if sel_proj:
        df = df[df["projeto_id"].isin(sel_proj)]
    if sel_cli:
        df = df[df["cliente"].isin(sel_cli)]
    if sel_disc:
        df = df[df["disciplina"].isin(sel_disc)]
    if sel_memb:
        df = df[df["membro_id"].isin(sel_memb)]
    if sel_tags:
        alvo = set(sel_tags)
        df = df[df["tags"].map(lambda x: bool(alvo & set(H.tags_lista(x))))]
    if sel_fat == "Faturável":
        df = df[df["faturavel"]]
    elif sel_fat == "Não faturável":
        df = df[~df["faturavel"]]

fin = u.ve_financeiro

# KPIs
k = st.columns(5 if fin else 3)
total_h = df["horas"].sum() if not df.empty else 0.0
fat_h = df.loc[df["faturavel"], "horas"].sum() if not df.empty else 0.0
k[0].metric("Horas", f"{total_h:,.2f}".replace(",", " "))
k[1].metric("Faturáveis", f"{fat_h:,.2f}".replace(",", " "),
            f"{fat_h / total_h:.0%}" if total_h else None, delta_color="off")
k[2].metric("Registos", len(df))
if fin:
    valor = df["valor"].sum() if not df.empty else 0.0
    custo = df["custo"].sum() if not df.empty else 0.0
    k[3].metric("Valor faturável", f"{valor:,.0f} €".replace(",", " "))
    k[4].metric("Custo interno", f"{custo:,.0f} €".replace(",", " "))

# ==========================================================================
# Separadores
# ==========================================================================
DIMENSOES = {
    "Projeto": "projeto",
    "Cliente": "cliente",
    "Disciplina": "disciplina",
    "Membro": "membro",
    "Tarefa": "tarefa",
    "Fase": "fase",
    "Tag": "tag",
    "Faturável": "faturavel_txt",
}

nomes_abas = ["Resumo", "Detalhado", "Semanal"] + (["Orçamento"] if u.gestor else [])
abas = st.tabs(nomes_abas)


def _preparar(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["faturavel_txt"] = d["faturavel"].map({True: "Faturável", False: "Não faturável"})
    d["projeto"] = d.apply(lambda r: f"{r['codigo']} — {r['projeto']}" if r["codigo"] else r["projeto"], axis=1)
    return d


def _agrupar(d: pd.DataFrame, dims: list[str]) -> pd.DataFrame:
    if "tag" in dims:
        d = d.assign(tag=d["tags"].map(lambda x: H.tags_lista(x) or ["(sem tag)"])).explode("tag")
    medidas = {"horas": "sum"}
    if fin:
        medidas.update({"valor": "sum", "custo": "sum"})
    g = d.groupby(dims, as_index=False).agg(medidas)
    total = g["horas"].sum()
    g["pct"] = g["horas"] / total if total else 0
    if fin:
        g["margem"] = g["valor"] - g["custo"]
    return g.sort_values("horas", ascending=False).reset_index(drop=True)


resumo_exp = pd.DataFrame()

# --------------------------------------------------------------------------
# Resumo
# --------------------------------------------------------------------------
with abas[0]:
    if df.empty:
        st.info("Sem registos para os filtros escolhidos.", icon="🔍")
    else:
        d = _preparar(df)
        c1, c2 = st.columns(2)
        dim1 = c1.selectbox("Agrupar por", list(DIMENSOES), index=0)
        dim2 = c2.selectbox("Depois por", ["(nenhum)"] + [x for x in DIMENSOES if x != dim1])
        dims = [DIMENSOES[dim1]] + ([DIMENSOES[dim2]] if dim2 != "(nenhum)" else [])
        g = _agrupar(d, dims)

        grafico = px.bar(
            g, x="horas", y=dims[0], color=dims[1] if len(dims) > 1 else None,
            orientation="h", labels={"horas": "Horas", dims[0]: dim1},
            height=max(260, 34 * g[dims[0]].nunique() + 80),
        )
        grafico.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(l=10, r=10, t=10, b=10),
                              legend_title_text=dim2 if len(dims) > 1 else None)
        st.plotly_chart(grafico, width="stretch")

        cfg = {
            dims[0]: dim1,
            "horas": st.column_config.NumberColumn("Horas", format="%.2f"),
            "pct": st.column_config.ProgressColumn("% do total", min_value=0, max_value=1, format="percent"),
        }
        if len(dims) > 1:
            cfg[dims[1]] = dim2
        if fin:
            cfg.update({
                "valor": st.column_config.NumberColumn("Valor (€)", format="%.2f"),
                "custo": st.column_config.NumberColumn("Custo (€)", format="%.2f"),
                "margem": st.column_config.NumberColumn("Margem (€)", format="%.2f"),
            })
        st.dataframe(g, hide_index=True, width="stretch", column_config=cfg)

        nomes_col = {dims[0]: dim1, "horas": "Horas", "pct": "% do total",
                     "valor": "Valor (€)", "custo": "Custo (€)", "margem": "Margem (€)"}
        if len(dims) > 1:
            nomes_col[dims[1]] = dim2
        resumo_exp = g.rename(columns=nomes_col)

# --------------------------------------------------------------------------
# Detalhado
# --------------------------------------------------------------------------
COLS_DET = ["data", "membro", "codigo", "projeto", "cliente", "tarefa", "disciplina", "fase",
            "hora_inicio", "hora_fim", "horas", "descricao", "tags", "faturavel"]
NOMES_DET = {"data": "Data", "membro": "Membro", "codigo": "Código", "projeto": "Projeto",
             "cliente": "Cliente", "tarefa": "Tarefa", "disciplina": "Disciplina", "fase": "Fase",
             "hora_inicio": "Início", "hora_fim": "Fim", "horas": "Horas", "descricao": "Descrição",
             "tags": "Tags", "faturavel": "Faturável", "taxa": "Taxa (€/h)", "valor": "Valor (€)",
             "custo": "Custo (€)"}
cols_det = COLS_DET + (["taxa", "valor", "custo"] if fin else [])

detalhe_exp = pd.DataFrame(columns=[NOMES_DET[c] for c in cols_det])
with abas[1]:
    if df.empty:
        st.info("Sem registos para os filtros escolhidos.", icon="🔍")
    else:
        det = df.sort_values(["data", "membro", "hora_inicio"])[cols_det]
        st.dataframe(
            det, hide_index=True, width="stretch",
            column_config={
                **{c: NOMES_DET[c] for c in cols_det},
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "horas": st.column_config.NumberColumn("Horas", format="%.2f"),
                "faturavel": st.column_config.CheckboxColumn("Faturável"),
                "taxa": st.column_config.NumberColumn("Taxa (€/h)", format="%.2f"),
                "valor": st.column_config.NumberColumn("Valor (€)", format="%.2f"),
                "custo": st.column_config.NumberColumn("Custo (€)", format="%.2f"),
            },
        )
        detalhe_exp = det.assign(faturavel=det["faturavel"].map({True: "Sim", False: "Não"})) \
                         .rename(columns=NOMES_DET)

# --------------------------------------------------------------------------
# Semanal (tabela cruzada)
# --------------------------------------------------------------------------
semanal_exp = pd.DataFrame()
with abas[2]:
    if df.empty:
        st.info("Sem registos para os filtros escolhidos.", icon="🔍")
    else:
        linhas_por = st.radio("Linhas", ["Membro", "Projeto", "Disciplina"], horizontal=True)
        d = _preparar(df)
        campo = DIMENSOES[linhas_por]
        dias_periodo = (fim - ini).days + 1
        if dias_periodo <= 31:
            d["coluna"] = d["data"].dt.strftime("%d/%m")
            ordem = [(ini + timedelta(days=i)).strftime("%d/%m") for i in range(dias_periodo)]
            st.caption("Colunas por dia.")
        else:
            d["coluna"] = d["data"].map(lambda x: f"Sem. {H.segunda(x.date()):%d/%m}")
            s0 = H.segunda(ini)
            ordem = []
            while s0 <= fim:
                ordem.append(f"Sem. {s0:%d/%m}")
                s0 += timedelta(days=7)
            st.caption("Períodos com mais de 31 dias: colunas por semana (segunda-feira indicada).")
        piv = d.pivot_table(index=campo, columns="coluna", values="horas", aggfunc="sum", fill_value=0.0)
        piv = piv.reindex(columns=ordem, fill_value=0.0)
        piv["Total"] = piv.sum(axis=1)
        piv = piv.sort_values("Total", ascending=False)
        piv.loc["Total"] = piv.sum()
        piv = piv.reset_index().rename(columns={campo: linhas_por})
        st.dataframe(
            piv, hide_index=True, width="stretch",
            column_config={c: st.column_config.NumberColumn(c, format="%.2f") for c in piv.columns[1:]},
        )
        semanal_exp = piv[piv[linhas_por] != "Total"]

# --------------------------------------------------------------------------
# Orçamento (gestores e administradores; todos os registos, sem filtro de datas)
# --------------------------------------------------------------------------
if u.gestor:
    with abas[3]:
        st.caption(
            "Horas orçadas vs. registadas desde o início, por todos os membros. "
            "Os filtros de período e membro não se aplicam aqui; o de projeto sim."
        )
        icone = {"OK": "🟢", "Atenção": "🟠", "Excedido": "🔴", "Sem orçamento": "⚪"}
        op = H.orcamento_projetos(todos, projetos)
        ot = H.orcamento_tarefas(todos, tarefas, projetos)
        if sel_proj:
            op = op[op["projeto_id"].isin(sel_proj)]
            ids_t = set(tarefas.loc[tarefas["projeto_id"].isin(sel_proj), "id"])
            ot = ot[ot["tarefa_id"].isin(ids_t)]

        cfg_orc = {
            "orcadas": st.column_config.NumberColumn("Orçadas (h)", format="%.1f"),
            "registadas": st.column_config.NumberColumn("Registadas (h)", format="%.1f"),
            "consumo": st.column_config.ProgressColumn("Consumo", min_value=0, max_value=1.2, format="percent"),
            "alerta": "Estado",
        }
        st.markdown("**Por projeto**")
        if op.empty:
            st.caption("Nenhum projeto com orçamento ou horas registadas.")
        else:
            st.dataframe(
                op.assign(alerta=op["alerta"].map(lambda a: f"{icone.get(a, '')} {a}"))
                  [["codigo", "projeto", "orcadas", "registadas", "consumo", "alerta"]],
                hide_index=True, width="stretch",
                column_config={"codigo": "Código", "projeto": "Projeto", **cfg_orc},
            )
        st.markdown("**Por tarefa**")
        if ot.empty:
            st.caption("Nenhuma tarefa com horas orçadas. Define-as em **Tarefas**.")
        else:
            st.dataframe(
                ot.assign(alerta=ot["alerta"].map(lambda a: f"{icone.get(a, '')} {a}"))
                  [["projeto", "tarefa", "disciplina", "orcadas", "registadas", "consumo", "alerta"]],
                hide_index=True, width="stretch",
                column_config={"projeto": "Projeto", "tarefa": "Tarefa", "disciplina": "Disc.", **cfg_orc},
            )

# ==========================================================================
# Exportação
# ==========================================================================
if not df.empty:
    st.divider()
    filtros = []
    if sel_proj:
        filtros.append("Projetos: " + ", ".join(nomes_proj[i] for i in sel_proj))
    if sel_cli:
        filtros.append("Clientes: " + ", ".join(sel_cli))
    if sel_disc:
        filtros.append("Disciplinas: " + ", ".join(sel_disc))
    if sel_memb:
        filtros.append("Membros: " + ", ".join(nomes_vis[i] for i in sel_memb))
    if sel_tags:
        filtros.append("Tags: " + ", ".join(sel_tags))
    if sel_fat != "Todos":
        filtros.append(sel_fat)
    info = [
        f"Período: {ini:%d/%m/%Y} a {fim:%d/%m/%Y}",
        "Filtros: " + ("; ".join(filtros) if filtros else "nenhum"),
        f"Gerado em {data.agora():%d/%m/%Y %H:%M} por {u.nome}",
    ]
    formatos = {
        "Horas": X.FMT_HORAS, "% do total": X.FMT_PCT, "Valor (€)": X.FMT_EURO,
        "Custo (€)": X.FMT_EURO, "Margem (€)": X.FMT_EURO, "Taxa (€/h)": '#,##0.00 "€"',
        "Data": X.FMT_DATA,
    }
    if resumo_exp.empty:
        resumo_exp = _agrupar(_preparar(df), ["projeto"]).rename(
            columns={"projeto": "Projeto", "horas": "Horas", "pct": "% do total",
                     "valor": "Valor (€)", "custo": "Custo (€)", "margem": "Margem (€)"}
        )
    xlsx = X.excel_relatorio("Relatório de horas", info, resumo_exp, detalhe_exp,
                             semanal_exp if not semanal_exp.empty else None, formatos)
    nome_base = f"horas_{ini:%Y%m%d}_{fim:%Y%m%d}"
    e1, e2, _ = st.columns([1, 1, 3])
    e1.download_button("⬇️ Excel", xlsx, f"{nome_base}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch", type="primary")
    e2.download_button("⬇️ CSV (detalhado)", X.csv_pt(detalhe_exp), f"{nome_base}.csv",
                       mime="text/csv", width="stretch")
