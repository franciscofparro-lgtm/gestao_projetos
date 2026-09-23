"""Gestão de projetos."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib import data, sessao
from lib.config import APP_ICON, ESTADOS_PROJETO

st.set_page_config(page_title="Projetos", page_icon=APP_ICON, layout="wide")

if not data.ligacao_ativa():
    st.error("Sem ligação ao Google Sheets. Configura os secrets na página inicial.")
    st.stop()

st.title("Projetos")

projetos = data.ler("projetos")
tarefas = data.ler("tarefas")
membros = data.ler("membros")
clientes = data.ler("clientes")
taxas = data.ler("taxas")
registos = data.ler("registos")

nomes_memb = dict(zip(membros["id"], membros["nome"])) if not membros.empty else {}
nomes_cli = dict(zip(clientes["id"], clientes["nome"])) if not clientes.empty else {}
utilizador = data.utilizador_atual()

u = sessao.utilizador(membros)
if u:
    sessao.cartao_lateral(u)
fin = bool(u and u.ve_financeiro)      # vê e edita taxa do projeto
pode_taxas = bool(u and u.admin)       # taxas específicas por membro

horas_por_proj = (
    registos[registos["estado"] != "Em curso"].groupby("projeto_id")["duracao_min"].sum() / 60
    if not registos.empty else pd.Series(dtype=float)
)


def _campos_horas(prefixo: str, reg=None):
    """Campos de orçamento e faturação. A taxa só aparece a gestores/admin."""
    c1, c2, c3 = st.columns(3)
    orc = c1.number_input(
        "Horas orçadas", min_value=0.0, step=10.0,
        value=float(reg["horas_orcadas"]) if reg is not None else 0.0,
        key=f"{prefixo}_orc", help="0 = sem orçamento. Alertas aos 80 % e 100 %.",
    )
    fat_atual = True if reg is None or not str(reg["faturavel"]).strip() else str(reg["faturavel"]) == "Sim"
    fat = c2.checkbox("Faturável por omissão", value=fat_atual, key=f"{prefixo}_fat",
                      help="Valor inicial da opção «faturável» nos registos deste projeto.")
    taxa = float(reg["taxa_hora"]) if reg is not None else 0.0
    if fin:
        taxa = c3.number_input("Taxa de faturação (€/h)", min_value=0.0, step=5.0, value=taxa,
                               key=f"{prefixo}_taxa", help="0 = usa a taxa de cada membro.")
    return orc, ("Sim" if fat else "Não"), taxa


def _cliente_select(col, atual_id: str = "", atual_txt: str = "", chave: str = ""):
    opcoes = [""] + list(nomes_cli.keys())
    idx = opcoes.index(atual_id) if atual_id in opcoes else 0
    ajuda = f"Valor antigo em texto: «{atual_txt}»" if atual_txt and not atual_id else None
    return col.selectbox(
        "Cliente", opcoes, index=idx, key=chave, help=ajuda,
        format_func=lambda i: nomes_cli.get(i, "(nenhum)"),
    )


aba_proj, aba_cli, aba_taxas = st.tabs(["Projetos", "Clientes", "Taxas por membro"])

# ==========================================================================
# Clientes
# ==========================================================================
with aba_cli:
    with st.form("novo_cliente", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 2])
        cn = c1.text_input("Nome", placeholder="SFEH")
        cnif = c2.text_input("NIF")
        ccont = c3.text_input("Contacto")
        if st.form_submit_button("Criar cliente", type="primary"):
            if not cn.strip():
                st.error("O nome é obrigatório.")
            elif cn.strip().lower() in {n.lower() for n in nomes_cli.values()}:
                st.error("Já existe um cliente com esse nome.")
            else:
                data.inserir("clientes", {"nome": cn.strip(), "nif": cnif.strip(), "contacto": ccont.strip()},
                             utilizador=utilizador)
                st.rerun()

    if clientes.empty:
        st.info("Ainda não há clientes registados.", icon="🏢")
    else:
        n_proj = projetos["cliente_id"].value_counts() if not projetos.empty else pd.Series(dtype=int)
        st.dataframe(
            clientes.assign(Projetos=clientes["id"].map(n_proj).fillna(0).astype(int))
                    [["nome", "nif", "contacto", "Projetos"]],
            hide_index=True, width="stretch",
            column_config={"nome": "Cliente", "nif": "NIF", "contacto": "Contacto"},
        )
        sel_c = st.selectbox("Editar cliente", list(nomes_cli), format_func=lambda i: nomes_cli[i])
        rc = clientes[clientes["id"] == sel_c].iloc[0]
        with st.form("editar_cliente"):
            c1, c2, c3 = st.columns([2, 1, 2])
            en = c1.text_input("Nome", value=rc["nome"])
            enif = c2.text_input("NIF", value=rc["nif"])
            econt = c3.text_input("Contacto", value=rc["contacto"])
            b1, b2 = st.columns([1, 4])
            if b1.form_submit_button("Guardar", type="primary"):
                data.atualizar("clientes", sel_c, {"nome": en.strip(), "nif": enif.strip(),
                                                   "contacto": econt.strip()}, utilizador=utilizador)
                st.rerun()
            if b2.form_submit_button("Eliminar cliente"):
                if int(n_proj.get(sel_c, 0)):
                    st.error("Há projetos associados a este cliente.")
                else:
                    data.eliminar("clientes", sel_c)
                    st.rerun()

# ==========================================================================
# Taxas específicas (projeto × membro)
# ==========================================================================
with aba_taxas:
    if not pode_taxas:
        st.info("Reservado a administradores.", icon="🔒")
    elif projetos.empty or membros.empty:
        st.caption("São precisos projetos e membros.")
    else:
        st.caption(
            "Precedência da taxa de faturação: específica (projeto × membro) → do projeto → "
            "do membro → 0. Deixa em branco ou a 0 para não sobrepor."
        )
        nomes_p = {r["id"]: (r["codigo"] or r["nome"]) for _, r in projetos.iterrows()}
        sel_tp = st.selectbox("Projeto", list(nomes_p), format_func=lambda i: nomes_p[i], key="tx_proj")
        atuais = taxas[taxas["projeto_id"] == sel_tp] if not taxas.empty else taxas
        mapa = dict(zip(atuais["membro_id"], atuais["taxa_hora"])) if not atuais.empty else {}
        grelha = pd.DataFrame({
            "membro_id": membros["id"],
            "Membro": membros["nome"],
            "Taxa (€/h)": [float(mapa.get(i, 0.0)) for i in membros["id"]],
        })
        ed = st.data_editor(
            grelha, hide_index=True, width="stretch", disabled=["Membro"],
            column_order=["Membro", "Taxa (€/h)"], key=f"taxas_{sel_tp}",
            column_config={"Taxa (€/h)": st.column_config.NumberColumn(min_value=0.0, step=5.0, format="%.2f")},
        )
        if st.button("Guardar taxas", type="primary"):
            por_membro = dict(zip(atuais["membro_id"], atuais["id"])) if not atuais.empty else {}
            novos, alterar, apagar = [], {}, []
            for _, r in ed.iterrows():
                v = float(r["Taxa (€/h)"] or 0)
                existente = por_membro.get(r["membro_id"])
                if v > 0 and existente:
                    if abs(v - float(mapa[r["membro_id"]])) > 1e-9:
                        alterar[existente] = {"taxa_hora": v}
                elif v > 0:
                    novos.append({"projeto_id": sel_tp, "membro_id": r["membro_id"], "taxa_hora": v})
                elif existente:
                    apagar.append(existente)
            data.inserir_lote("taxas", novos, utilizador=utilizador)
            data.atualizar_lote("taxas", alterar, utilizador=utilizador)
            data.eliminar_lote("taxas", apagar)
            st.session_state.pop(f"taxas_{sel_tp}", None)
            st.rerun()

with aba_proj:
    # --------------------------------------------------------------------------
    # Novo projeto
    # --------------------------------------------------------------------------
    with st.expander("Novo projeto", expanded=projetos.empty):
        with st.form("novo_projeto", clear_on_submit=True):
            c1, c2 = st.columns(2)
            codigo = c1.text_input("Código", placeholder="HLO-A")
            nome = c2.text_input("Nome", placeholder="Hospital de Lisboa Oriental — Parcela A")

            c3, c4, c5 = st.columns(3)
            cliente_id = _cliente_select(c3, chave="novo_cli")
            estado = c4.selectbox("Estado", ESTADOS_PROJETO)
            responsavel = c5.selectbox(
                "Responsável", options=[""] + list(nomes_memb.keys()),
                format_func=lambda i: nomes_memb.get(i, "(nenhum)"),
            )

            c6, c7 = st.columns(2)
            inicio = c6.date_input("Início", value=date.today(), format="DD/MM/YYYY")
            fim = c7.date_input("Fim previsto", value=None, format="DD/MM/YYYY")

            orc, fat, taxa = _campos_horas("novo")
            notas = st.text_area("Notas", height=80)

            if st.form_submit_button("Criar projeto", type="primary"):
                if not nome.strip():
                    st.error("O nome é obrigatório.")
                elif fim and inicio and fim < inicio:
                    st.error("A data de fim é anterior à de início.")
                else:
                    data.inserir(
                        "projetos",
                        {
                            "codigo": codigo.strip(),
                            "nome": nome.strip(),
                            "cliente": nomes_cli.get(cliente_id, ""),
                            "cliente_id": cliente_id,
                            "horas_orcadas": orc,
                            "taxa_hora": taxa,
                            "faturavel": fat,
                            "estado": estado,
                            "data_inicio": inicio,
                            "data_fim": fim,
                            "responsavel_id": responsavel,
                            "notas": notas.strip(),
                        },
                        utilizador=utilizador,
                    )
                    st.success(f"Projeto «{nome}» criado.")
                    st.rerun()

    st.divider()

    if projetos.empty:
        st.info("Ainda não há projetos registados.", icon="📁")
        st.stop()

    # --------------------------------------------------------------------------
    # Lista
    # --------------------------------------------------------------------------
    contagem = tarefas["projeto_id"].value_counts() if not tarefas.empty else pd.Series(dtype=int)

    vista = projetos.assign(
        Tarefas=projetos["id"].map(contagem).fillna(0).astype(int),
        Responsável=projetos["responsavel_id"].map(nomes_memb).fillna("—"),
        cliente=[nomes_cli.get(ci) or ct for ci, ct in zip(projetos["cliente_id"], projetos["cliente"])],
        Registadas=projetos["id"].map(horas_por_proj).fillna(0.0),
    )[["codigo", "nome", "cliente", "estado", "data_inicio", "data_fim", "Responsável", "Tarefas",
       "horas_orcadas", "Registadas"]]

    st.dataframe(
        vista,
        hide_index=True,
        width="stretch",
        column_config={
            "codigo": "Código",
            "nome": "Nome",
            "cliente": "Cliente",
            "estado": "Estado",
            "data_inicio": st.column_config.DateColumn("Início", format="DD/MM/YYYY"),
            "data_fim": st.column_config.DateColumn("Fim", format="DD/MM/YYYY"),
            "horas_orcadas": st.column_config.NumberColumn("Orçadas (h)", format="%.0f"),
            "Registadas": st.column_config.NumberColumn("Registadas (h)", format="%.1f"),
        },
    )

    # --------------------------------------------------------------------------
    # Edição
    # --------------------------------------------------------------------------
    st.subheader("Editar projeto")

    opcoes = dict(zip(projetos["id"], projetos["nome"]))
    sel = st.selectbox("Projeto", options=list(opcoes.keys()), format_func=lambda i: opcoes[i])
    registo = projetos[projetos["id"] == sel].iloc[0]

    with st.form("editar_projeto"):
        c1, c2 = st.columns(2)
        e_codigo = c1.text_input("Código", value=str(registo["codigo"] or ""))
        e_nome = c2.text_input("Nome", value=str(registo["nome"] or ""))

        c3, c4, c5 = st.columns(3)
        e_cliente_id = _cliente_select(c3, registo["cliente_id"], registo["cliente"], chave=f"ed_cli_{sel}")
        e_estado = c4.selectbox(
            "Estado", ESTADOS_PROJETO,
            index=ESTADOS_PROJETO.index(registo["estado"]) if registo["estado"] in ESTADOS_PROJETO else 0,
        )
        lista_resp = [""] + list(nomes_memb.keys())
        e_resp = c5.selectbox(
            "Responsável", options=lista_resp,
            index=lista_resp.index(registo["responsavel_id"]) if registo["responsavel_id"] in lista_resp else 0,
            format_func=lambda i: nomes_memb.get(i, "(nenhum)"),
        )

        c6, c7 = st.columns(2)
        e_inicio = c6.date_input(
            "Início",
            value=registo["data_inicio"].date() if pd.notna(registo["data_inicio"]) else None,
            format="DD/MM/YYYY",
        )
        e_fim = c7.date_input(
            "Fim previsto",
            value=registo["data_fim"].date() if pd.notna(registo["data_fim"]) else None,
            format="DD/MM/YYYY",
        )

        e_orc, e_fat, e_taxa = _campos_horas(f"ed_{sel}", registo)
        e_notas = st.text_area("Notas", value=str(registo["notas"] or ""), height=80)

        g1, g2 = st.columns([1, 4])
        guardar = g1.form_submit_button("Guardar", type="primary")
        eliminar = g2.form_submit_button("Eliminar projeto")

        if guardar:
            data.atualizar(
                "projetos", sel,
                {
                    "codigo": e_codigo.strip(),
                    "nome": e_nome.strip(),
                    "cliente": nomes_cli.get(e_cliente_id, "") or (registo["cliente"] if not e_cliente_id else ""),
                    "cliente_id": e_cliente_id,
                    "horas_orcadas": e_orc,
                    "taxa_hora": e_taxa,
                    "faturavel": e_fat,
                    "estado": e_estado,
                    "data_inicio": e_inicio,
                    "data_fim": e_fim,
                    "responsavel_id": e_resp,
                    "notas": e_notas.strip(),
                },
                utilizador=utilizador,
            )
            st.success("Alterações guardadas.")
            st.rerun()

        if eliminar:
            ligadas = int(contagem.get(sel, 0))
            com_horas = float(horas_por_proj.get(sel, 0))
            if com_horas:
                st.error(
                    f"Este projeto tem {com_horas:.1f} h registadas. Em vez de eliminar, "
                    "muda o estado para «Arquivado»."
                )
            elif ligadas:
                st.error(
                    f"Este projeto tem {ligadas} tarefa(s) associada(s). "
                    "Elimina ou reatribui as tarefas primeiro."
                )
            else:
                data.eliminar("projetos", sel)
                st.success("Projeto eliminado.")
                st.rerun()
