"""Gestão de equipas e membros."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib import data, sessao
from lib.config import APP_ICON, HORAS_SEMANA_OMISSAO, PERFIL_DESC, PERFIS

st.set_page_config(page_title="Equipas", page_icon=APP_ICON, layout="wide")

if not data.ligacao_ativa():
    st.error("Sem ligação ao Google Sheets. Configura os secrets na página inicial.")
    st.stop()

st.title("Equipas")

equipas = data.ler("equipas")
membros = data.ler("membros")
tarefas = data.ler("tarefas")
registos = data.ler("registos")
utilizador = data.utilizador_atual()

u = sessao.utilizador(membros)
if u:
    sessao.cartao_lateral(u)
# Perfis e custos: só admin. Antes de existir qualquer admin, qualquer pessoa
# com acesso à app pode fazer a configuração inicial.
pode_gerir = bool(u and u.admin) or not sessao.existe_admin(membros)
if not sessao.existe_admin(membros):
    st.info(
        "Ainda não há administradores. Ao criar os membros, atribui o perfil «admin» "
        "a pelo menos uma pessoa (com o email exato com que entra na aplicação).",
        icon="🛠️",
    )


def _email_em_uso(email: str, exceto: str = "") -> bool:
    e = email.strip().lower()
    if not e or membros.empty:
        return False
    outros = membros[membros["id"] != exceto]
    return bool((outros["email"].astype(str).str.strip().str.lower() == e).any())


def _campos_gestao(prefixo: str, reg=None) -> dict:
    """Perfil, horas semanais, custo e taxa. Devolve {} se o utilizador não os pode gerir."""
    if not pode_gerir:
        return {}
    c1, c2, c3, c4 = st.columns(4)
    atual = str(reg["perfil"]).lower() if reg is not None else "colaborador"
    perfil = c1.selectbox(
        "Perfil", PERFIS, index=PERFIS.index(atual) if atual in PERFIS else 0,
        key=f"{prefixo}_perfil", help=" · ".join(f"{k}: {v}" for k, v in PERFIL_DESC.items()),
    )
    hs = c2.number_input(
        "Horas/semana", min_value=0.0, max_value=60.0, step=1.0, key=f"{prefixo}_hs",
        value=float(reg["horas_semana"] or HORAS_SEMANA_OMISSAO) if reg is not None else float(HORAS_SEMANA_OMISSAO),
    )
    custo = c3.number_input(
        "Custo interno (€/h)", min_value=0.0, step=1.0, key=f"{prefixo}_custo",
        value=float(reg["custo_hora"]) if reg is not None else 0.0,
    )
    taxa = c4.number_input(
        "Taxa de faturação (€/h)", min_value=0.0, step=5.0, key=f"{prefixo}_taxa",
        value=float(reg["taxa_hora"]) if reg is not None else 0.0,
        help="Usada quando o projeto não tem taxa própria.",
    )
    return {"perfil": perfil, "horas_semana": hs, "custo_hora": custo, "taxa_hora": taxa}

aba_equipas, aba_membros, aba_carga = st.tabs(["Equipas", "Membros", "Carga de trabalho"])

# ==========================================================================
# Equipas
# ==========================================================================
with aba_equipas:
    with st.expander("Nova equipa", expanded=equipas.empty):
        with st.form("nova_equipa", clear_on_submit=True):
            nome = st.text_input("Nome", placeholder="Mecânica / MEP")
            descricao = st.text_input("Descrição", placeholder="Gases medicinais, ar comprimido, AVAC")
            if st.form_submit_button("Criar equipa", type="primary"):
                if not nome.strip():
                    st.error("O nome é obrigatório.")
                else:
                    data.inserir(
                        "equipas",
                        {"nome": nome.strip(), "descricao": descricao.strip()},
                        utilizador=utilizador,
                    )
                    st.success("Equipa criada.")
                    st.rerun()

    if equipas.empty:
        st.info("Ainda não há equipas registadas.", icon="👥")
    else:
        contagem = membros["equipa_id"].value_counts() if not membros.empty else pd.Series(dtype=int)
        vista = equipas.assign(Membros=equipas["id"].map(contagem).fillna(0).astype(int))[
            ["nome", "descricao", "Membros"]
        ]
        st.dataframe(
            vista, hide_index=True, width="stretch",
            column_config={"nome": "Equipa", "descricao": "Descrição"},
        )

        st.subheader("Editar equipa")
        opcoes = dict(zip(equipas["id"], equipas["nome"]))
        sel = st.selectbox("Equipa", list(opcoes.keys()), format_func=lambda i: opcoes[i])
        registo = equipas[equipas["id"] == sel].iloc[0]

        with st.form("editar_equipa"):
            e_nome = st.text_input("Nome", value=str(registo["nome"] or ""))
            e_desc = st.text_input("Descrição", value=str(registo["descricao"] or ""))
            g1, g2 = st.columns([1, 4])
            if g1.form_submit_button("Guardar", type="primary"):
                data.atualizar(
                    "equipas", sel,
                    {"nome": e_nome.strip(), "descricao": e_desc.strip()},
                    utilizador=utilizador,
                )
                st.success("Alterações guardadas.")
                st.rerun()
            if g2.form_submit_button("Eliminar equipa"):
                ligados = int(contagem.get(sel, 0))
                if ligados:
                    st.error(f"Esta equipa tem {ligados} membro(s). Remove-os primeiro.")
                else:
                    data.eliminar("equipas", sel)
                    st.success("Equipa eliminada.")
                    st.rerun()

# ==========================================================================
# Membros
# ==========================================================================
with aba_membros:
    if equipas.empty:
        st.warning("Cria primeiro uma equipa.", icon="👥")
    else:
        nomes_eq = dict(zip(equipas["id"], equipas["nome"]))

        with st.expander("Novo membro", expanded=membros.empty):
            with st.form("novo_membro", clear_on_submit=True):
                c1, c2 = st.columns(2)
                m_nome = c1.text_input("Nome")
                m_email = c2.text_input("Email")
                c3, c4, c5 = st.columns(3)
                m_equipa = c3.selectbox(
                    "Equipa", list(nomes_eq.keys()), format_func=lambda i: nomes_eq[i]
                )
                m_funcao = c4.text_input("Função", placeholder="Engenheiro mecânico")
                m_ativo = c5.checkbox("Ativo", value=True)
                m_gestao = _campos_gestao("novo")

                if not pode_gerir:
                    st.caption("🔒 Só administradores podem acrescentar membros.")
                if st.form_submit_button("Adicionar membro", type="primary", disabled=not pode_gerir):
                    if not m_nome.strip():
                        st.error("O nome é obrigatório.")
                    elif _email_em_uso(m_email):
                        st.error("Esse email já está associado a outro membro.")
                    else:
                        data.inserir(
                            "membros",
                            {
                                "equipa_id": m_equipa,
                                "nome": m_nome.strip(),
                                "email": m_email.strip(),
                                "funcao": m_funcao.strip(),
                                "ativo": "Sim" if m_ativo else "Não",
                                "perfil": "colaborador",
                                "horas_semana": HORAS_SEMANA_OMISSAO,
                                **m_gestao,
                            },
                            utilizador=utilizador,
                        )
                        st.success("Membro adicionado.")
                        st.rerun()

        if membros.empty:
            st.info("Ainda não há membros registados.", icon="🧑‍💼")
        else:
            colunas_v = ["nome", "Equipa", "funcao", "email", "ativo", "perfil", "horas_semana"]
            if pode_gerir:
                colunas_v += ["custo_hora", "taxa_hora"]
            vista = membros.assign(
                Equipa=membros["equipa_id"].map(nomes_eq),
                perfil=membros["perfil"].replace("", "colaborador"),
            )[colunas_v]
            st.dataframe(
                vista, hide_index=True, width="stretch",
                column_config={
                    "nome": "Nome", "funcao": "Função",
                    "email": "Email", "ativo": "Ativo", "perfil": "Perfil",
                    "horas_semana": st.column_config.NumberColumn("h/semana", format="%.0f"),
                    "custo_hora": st.column_config.NumberColumn("Custo €/h", format="%.2f"),
                    "taxa_hora": st.column_config.NumberColumn("Taxa €/h", format="%.2f"),
                },
            )

            st.subheader("Editar membro")
            opcoes = dict(zip(membros["id"], membros["nome"]))
            sel_m = st.selectbox("Membro", list(opcoes.keys()), format_func=lambda i: opcoes[i])
            reg = membros[membros["id"] == sel_m].iloc[0]
            lista_eq = list(nomes_eq.keys())

            with st.form("editar_membro"):
                c1, c2 = st.columns(2)
                e_nome = c1.text_input("Nome", value=str(reg["nome"] or ""))
                e_email = c2.text_input(
                    "Email", value=str(reg["email"] or ""), disabled=not pode_gerir,
                    help="O email identifica a pessoa no início de sessão. Só administradores o alteram.",
                )
                c3, c4, c5 = st.columns(3)
                e_equipa = c3.selectbox(
                    "Equipa", lista_eq,
                    index=lista_eq.index(reg["equipa_id"]) if reg["equipa_id"] in lista_eq else 0,
                    format_func=lambda i: nomes_eq[i],
                )
                e_funcao = c4.text_input("Função", value=str(reg["funcao"] or ""))
                e_ativo = c5.checkbox("Ativo", value=str(reg["ativo"]).strip().lower() != "não",
                                      disabled=not pode_gerir)
                e_gestao = _campos_gestao(f"ed_{sel_m}", reg)

                g1, g2 = st.columns([1, 4])
                if g1.form_submit_button("Guardar", type="primary"):
                    if pode_gerir and _email_em_uso(e_email, exceto=sel_m):
                        st.error("Esse email já está associado a outro membro.")
                        st.stop()
                    data.atualizar(
                        "membros", sel_m,
                        {
                            "equipa_id": e_equipa,
                            "nome": e_nome.strip(),
                            "email": e_email.strip(),
                            "funcao": e_funcao.strip(),
                            "ativo": "Sim" if e_ativo else "Não",
                            **e_gestao,
                        },
                        utilizador=utilizador,
                    )
                    st.success("Alterações guardadas.")
                    st.rerun()
                if g2.form_submit_button("Remover membro", disabled=not pode_gerir):
                    atribuidas = (
                        int((tarefas["responsavel_id"] == sel_m).sum()) if not tarefas.empty else 0
                    )
                    com_horas = (
                        int((registos["membro_id"] == sel_m).sum()) if not registos.empty else 0
                    )
                    if com_horas:
                        st.error(
                            f"Este membro tem {com_horas} registo(s) de horas. Desmarca «Ativo» "
                            "em vez de o remover, para manter o histórico."
                        )
                    elif atribuidas:
                        st.error(
                            f"Este membro tem {atribuidas} tarefa(s) atribuída(s). "
                            "Reatribui-as primeiro."
                        )
                    else:
                        data.eliminar("membros", sel_m)
                        st.success("Membro removido.")
                        st.rerun()

# ==========================================================================
# Carga de trabalho
# ==========================================================================
with aba_carga:
    if membros.empty or tarefas.empty:
        st.info("São precisos membros e tarefas para calcular a carga.", icon="📊")
    else:
        hoje = pd.Timestamp(date.today())
        abertas = tarefas[tarefas["estado"] != "Concluída"]

        linhas = []
        for _, m in membros.iterrows():
            minhas = abertas[abertas["responsavel_id"] == m["id"]]
            atrasadas = minhas[minhas["data_fim"] < hoje]
            linhas.append(
                {
                    "Membro": m["nome"],
                    "Função": m["funcao"],
                    "Tarefas abertas": len(minhas),
                    "Em atraso": len(atrasadas),
                    "Progresso médio": (
                        round(pd.to_numeric(minhas["progresso"], errors="coerce").fillna(0).mean())
                        if len(minhas) else 0
                    ),
                }
            )

        carga = pd.DataFrame(linhas).sort_values("Tarefas abertas", ascending=False)
        st.dataframe(
            carga, hide_index=True, width="stretch",
            column_config={
                "Progresso médio": st.column_config.ProgressColumn(
                    "Progresso médio", min_value=0, max_value=100, format="%d%%"
                ),
            },
        )

        sem_dono = int((abertas["responsavel_id"].fillna("") == "").sum())
        if sem_dono:
            st.warning(f"{sem_dono} tarefa(s) aberta(s) sem responsável atribuído.", icon="⚠️")
