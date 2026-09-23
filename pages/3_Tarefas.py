"""Gestão de tarefas."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import data
from lib.config import (
    APP_ICON,
    DISCIPLINAS_KEYS,
    ESTADOS_TAREFA,
    FASES,
    rotulo_disciplina,
)

st.set_page_config(page_title="Tarefas", page_icon=APP_ICON, layout="wide")

if not data.ligacao_ativa():
    st.error("Sem ligação ao Google Sheets. Configura os secrets na página inicial.")
    st.stop()

st.title("Tarefas")

projetos = data.ler("projetos")
tarefas = data.ler("tarefas")
membros = data.ler("membros")
registos = data.ler("registos")

horas_por_tarefa = (
    registos[registos["estado"] != "Em curso"].groupby("tarefa_id")["duracao_min"].sum() / 60
    if not registos.empty else pd.Series(dtype=float)
)

if projetos.empty:
    st.warning("Cria primeiro um projeto no separador **Projetos**.", icon="📁")
    st.stop()

nomes_proj = dict(zip(projetos["id"], projetos["nome"]))
nomes_memb = dict(zip(membros["id"], membros["nome"])) if not membros.empty else {}
utilizador = data.utilizador_atual()

# --------------------------------------------------------------------------
# Nova tarefa
# --------------------------------------------------------------------------
with st.expander("Nova tarefa", expanded=tarefas.empty):
    with st.form("nova_tarefa", clear_on_submit=True):
        c1, c2 = st.columns([2, 3])
        projeto = c1.selectbox(
            "Projeto", options=list(nomes_proj.keys()), format_func=lambda i: nomes_proj[i]
        )
        nome = c2.text_input("Tarefa", placeholder="Revisão do MQT — rede de gases medicinais")

        c3, c4, c5 = st.columns(3)
        disciplina = c3.selectbox("Disciplina", DISCIPLINAS_KEYS, format_func=rotulo_disciplina)
        fase = c4.selectbox("Fase", FASES)
        responsavel = c5.selectbox(
            "Responsável", options=[""] + list(nomes_memb.keys()),
            format_func=lambda i: nomes_memb.get(i, "(por atribuir)"),
        )

        c6, c7, c8, c9 = st.columns(4)
        inicio = c6.date_input("Início", value=date.today(), format="DD/MM/YYYY")
        fim = c7.date_input("Fim", value=date.today() + timedelta(days=14), format="DD/MM/YYYY")
        progresso = c8.number_input("Progresso (%)", 0, 100, 0, step=5)
        estado = c9.selectbox("Estado", ESTADOS_TAREFA)

        c10, c11 = st.columns([1, 3])
        orcadas = c10.number_input("Horas orçadas", min_value=0.0, step=5.0, value=0.0,
                                   help="0 = sem orçamento. Alertas aos 80 % e 100 %.")
        notas = c11.text_area("Notas", height=70)

        if st.form_submit_button("Criar tarefa", type="primary"):
            if not nome.strip():
                st.error("O nome da tarefa é obrigatório.")
            elif fim < inicio:
                st.error("A data de fim é anterior à de início.")
            else:
                data.inserir(
                    "tarefas",
                    {
                        "projeto_id": projeto,
                        "nome": nome.strip(),
                        "disciplina": disciplina,
                        "fase": fase,
                        "responsavel_id": responsavel,
                        "data_inicio": inicio,
                        "data_fim": fim,
                        "progresso": progresso,
                        "estado": estado,
                        "horas_orcadas": orcadas,
                        "notas": notas.strip(),
                    },
                    utilizador=utilizador,
                )
                st.success("Tarefa criada.")
                st.rerun()

st.divider()

if tarefas.empty:
    st.info("Ainda não há tarefas registadas.", icon="📋")
    st.stop()

# --------------------------------------------------------------------------
# Filtros
# --------------------------------------------------------------------------
f1, f2, f3, f4 = st.columns(4)
sel_proj = f1.multiselect(
    "Projeto", options=list(nomes_proj.keys()),
    format_func=lambda i: nomes_proj[i], placeholder="Todos",
)
sel_disc = f2.multiselect(
    "Disciplina", options=DISCIPLINAS_KEYS, format_func=rotulo_disciplina, placeholder="Todas"
)
sel_resp = f3.multiselect(
    "Responsável", options=list(nomes_memb.keys()),
    format_func=lambda i: nomes_memb.get(i, i), placeholder="Todos",
)
sel_estado = f4.multiselect("Estado", options=ESTADOS_TAREFA, placeholder="Todos")

vista = tarefas.copy()
if sel_proj:
    vista = vista[vista["projeto_id"].isin(sel_proj)]
if sel_disc:
    vista = vista[vista["disciplina"].isin(sel_disc)]
if sel_resp:
    vista = vista[vista["responsavel_id"].isin(sel_resp)]
if sel_estado:
    vista = vista[vista["estado"].isin(sel_estado)]

st.caption(f"{len(vista)} de {len(tarefas)} tarefas")

tabela = vista.assign(
    Projeto=vista["projeto_id"].map(nomes_proj),
    Responsável=vista["responsavel_id"].map(nomes_memb).fillna("—"),
    Registadas=vista["id"].map(horas_por_tarefa).fillna(0.0),
)[["Projeto", "nome", "disciplina", "fase", "Responsável",
   "data_inicio", "data_fim", "progresso", "estado", "horas_orcadas", "Registadas"]]

st.dataframe(
    tabela,
    hide_index=True,
    width="stretch",
    column_config={
        "nome": "Tarefa",
        "disciplina": "Disc.",
        "fase": "Fase",
        "data_inicio": st.column_config.DateColumn("Início", format="DD/MM/YYYY"),
        "data_fim": st.column_config.DateColumn("Fim", format="DD/MM/YYYY"),
        "progresso": st.column_config.ProgressColumn(
            "Progresso", min_value=0, max_value=100, format="%d%%"
        ),
        "estado": "Estado",
        "horas_orcadas": st.column_config.NumberColumn("Orçadas (h)", format="%.0f"),
        "Registadas": st.column_config.NumberColumn("Registadas (h)", format="%.1f"),
    },
)

# --------------------------------------------------------------------------
# Edição
# --------------------------------------------------------------------------
st.subheader("Editar tarefa")

if vista.empty:
    st.caption("Nenhuma tarefa corresponde aos filtros ativos.")
    st.stop()

opcoes = {
    r["id"]: f"{nomes_proj.get(r['projeto_id'], '?')} · {r['nome']}"
    for _, r in vista.iterrows()
}
sel = st.selectbox("Tarefa", options=list(opcoes.keys()), format_func=lambda i: opcoes[i])
registo = tarefas[tarefas["id"] == sel].iloc[0]


def _indice(lista, valor, omissao=0):
    return lista.index(valor) if valor in lista else omissao


with st.form("editar_tarefa"):
    c1, c2 = st.columns([2, 3])
    e_proj = c1.selectbox(
        "Projeto", options=list(nomes_proj.keys()),
        index=_indice(list(nomes_proj.keys()), registo["projeto_id"]),
        format_func=lambda i: nomes_proj[i],
    )
    e_nome = c2.text_input("Tarefa", value=str(registo["nome"] or ""))

    c3, c4, c5 = st.columns(3)
    e_disc = c3.selectbox(
        "Disciplina", DISCIPLINAS_KEYS,
        index=_indice(DISCIPLINAS_KEYS, registo["disciplina"]),
        format_func=rotulo_disciplina,
    )
    e_fase = c4.selectbox("Fase", FASES, index=_indice(FASES, registo["fase"]))
    lista_resp = [""] + list(nomes_memb.keys())
    e_resp = c5.selectbox(
        "Responsável", options=lista_resp,
        index=_indice(lista_resp, registo["responsavel_id"]),
        format_func=lambda i: nomes_memb.get(i, "(por atribuir)"),
    )

    c6, c7, c8, c9 = st.columns(4)
    e_inicio = c6.date_input(
        "Início",
        value=registo["data_inicio"].date() if pd.notna(registo["data_inicio"]) else date.today(),
        format="DD/MM/YYYY",
    )
    e_fim = c7.date_input(
        "Fim",
        value=registo["data_fim"].date() if pd.notna(registo["data_fim"]) else date.today(),
        format="DD/MM/YYYY",
    )
    e_prog = c8.slider("Progresso (%)", 0, 100, int(registo["progresso"] or 0), step=5)
    e_estado = c9.selectbox(
        "Estado", ESTADOS_TAREFA, index=_indice(ESTADOS_TAREFA, registo["estado"])
    )

    c10, c11 = st.columns([1, 3])
    e_orc = c10.number_input("Horas orçadas", min_value=0.0, step=5.0,
                             value=float(registo["horas_orcadas"] or 0))
    e_notas = c11.text_area("Notas", value=str(registo["notas"] or ""), height=70)

    g1, g2, g3 = st.columns([1, 1, 4])
    guardar = g1.form_submit_button("Guardar", type="primary")
    concluir = g2.form_submit_button("Marcar concluída")
    eliminar = g3.form_submit_button("Eliminar")

    if guardar or concluir:
        if e_fim < e_inicio:
            st.error("A data de fim é anterior à de início.")
        else:
            alteracoes = {
                "projeto_id": e_proj,
                "nome": e_nome.strip(),
                "disciplina": e_disc,
                "fase": e_fase,
                "responsavel_id": e_resp,
                "data_inicio": e_inicio,
                "data_fim": e_fim,
                "progresso": 100 if concluir else e_prog,
                "estado": "Concluída" if concluir else e_estado,
                "horas_orcadas": e_orc,
                "notas": e_notas.strip(),
            }
            data.atualizar("tarefas", sel, alteracoes, utilizador=utilizador)
            st.success("Alterações guardadas.")
            st.rerun()

    if eliminar:
        com_horas = float(horas_por_tarefa.get(sel, 0))
        if com_horas:
            st.error(
                f"Esta tarefa tem {com_horas:.1f} h registadas. Marca-a como concluída "
                "em vez de a eliminar."
            )
        else:
            data.eliminar("tarefas", sel)
            st.success("Tarefa eliminada.")
            st.rerun()

st.caption(
    f"Última alteração por {registo['atualizado_por'] or '—'} "
    f"em {registo['atualizado_em'] or '—'}"
)
