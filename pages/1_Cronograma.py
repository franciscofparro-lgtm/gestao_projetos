"""Cronograma (Gantt)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import data
from lib.config import APP_ICON, DISCIPLINAS_KEYS, rotulo_disciplina
from lib.gantt import construir_gantt

st.set_page_config(page_title="Cronograma", page_icon=APP_ICON, layout="wide")

if not data.ligacao_ativa():
    st.error("Sem ligação ao Google Sheets. Configura os secrets na página inicial.")
    st.stop()

st.title("Cronograma")

projetos = data.ler("projetos")
tarefas = data.ler("tarefas")
membros = data.ler("membros")

if tarefas.empty:
    st.info("Ainda não existem tarefas. Cria-as no separador **Tarefas**.", icon="📋")
    st.stop()

# --------------------------------------------------------------------------
# Filtros
# --------------------------------------------------------------------------
nomes_proj = dict(zip(projetos["id"], projetos["nome"])) if not projetos.empty else {}
nomes_memb = dict(zip(membros["id"], membros["nome"])) if not membros.empty else {}

f1, f2, f3, f4 = st.columns([2, 2, 2, 1.4])

sel_proj = f1.multiselect(
    "Projetos", options=list(nomes_proj.keys()),
    format_func=lambda i: nomes_proj.get(i, i), placeholder="Todos",
)
sel_disc = f2.multiselect(
    "Disciplinas", options=DISCIPLINAS_KEYS,
    format_func=rotulo_disciplina, placeholder="Todas",
)
sel_resp = f3.multiselect(
    "Responsáveis", options=list(nomes_memb.keys()),
    format_func=lambda i: nomes_memb.get(i, i), placeholder="Todos",
)
escala = f4.radio("Escala", ["dia", "semana", "mês"], index=1, horizontal=True)

o1, o2, o3 = st.columns([1, 1, 4])
mostrar_progresso = o1.toggle("Progresso", value=True)
marcar_atrasos = o2.toggle("Realçar atrasos", value=True)
esconder_concluidas = o3.toggle("Esconder concluídas", value=False)

filtradas = tarefas.copy()
if sel_proj:
    filtradas = filtradas[filtradas["projeto_id"].isin(sel_proj)]
if sel_disc:
    filtradas = filtradas[filtradas["disciplina"].isin(sel_disc)]
if sel_resp:
    filtradas = filtradas[filtradas["responsavel_id"].isin(sel_resp)]
if esconder_concluidas:
    filtradas = filtradas[filtradas["estado"] != "Concluída"]

st.caption(f"{len(filtradas)} de {len(tarefas)} tarefas visíveis")

# --------------------------------------------------------------------------
# Gráfico
# --------------------------------------------------------------------------
fig = construir_gantt(
    filtradas, projetos, membros,
    escala=escala,
    mostrar_progresso=mostrar_progresso,
    marcar_atrasos=marcar_atrasos,
)

if fig is None:
    st.warning("Nenhuma tarefa com datas de início e fim válidas para os filtros ativos.")
    st.stop()

st.plotly_chart(
    fig,
    width="stretch",
    config={
        "displaylogo": False,
        "toImageButtonOptions": {
            "format": "png", "filename": "cronograma", "scale": 2,
        },
    },
)

st.caption(
    "Passa o rato sobre o ícone da máquina fotográfica, no canto superior direito "
    "do gráfico, para descarregar em PNG."
)

# --------------------------------------------------------------------------
# Exportação
# --------------------------------------------------------------------------
with st.expander("Exportar"):
    exp = filtradas.copy()
    exp["projeto"] = exp["projeto_id"].map(nomes_proj)
    exp["responsavel"] = exp["responsavel_id"].map(nomes_memb)
    colunas = [
        "projeto", "nome", "disciplina", "fase", "responsavel",
        "data_inicio", "data_fim", "progresso", "estado", "notas",
    ]
    exp = exp[[c for c in colunas if c in exp.columns]]
    for col in ("data_inicio", "data_fim"):
        if col in exp.columns:
            exp[col] = pd.to_datetime(exp[col]).dt.strftime("%d/%m/%Y")

    csv = exp.to_csv(index=False, sep=";", encoding="utf-8-sig")
    st.download_button(
        "Descarregar CSV (Excel PT)",
        data=csv.encode("utf-8-sig"),
        file_name="cronograma.csv",
        mime="text/csv",
        width="stretch",
    )
    st.caption(
        "Separador ponto e vírgula com BOM UTF-8 — abre diretamente no Excel "
        "português sem passar pelo assistente de importação."
    )
