"""Aprovação de semanas submetidas e fecho de períodos (gestores e administradores)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from lib import data, sessao
from lib import horas as H
from lib.config import APP_ICON, LIMITE_HORAS_REGISTO

st.set_page_config(page_title="Aprovações", page_icon=APP_ICON, layout="wide")

if not data.ligacao_ativa():
    st.error("Sem ligação ao Google Sheets. Configura os secrets na página inicial.")
    st.stop()

membros = data.ler("membros")
u = sessao.exigir_utilizador(membros)
sessao.cartao_lateral(u)

st.title("Aprovações")

if not u.gestor:
    st.info("Esta página é reservada a gestores e administradores.", icon="🔒")
    st.stop()

projetos = data.ler("projetos")
tarefas = data.ler("tarefas")
registos = data.ler("registos")
submissoes = data.ler("submissoes")
periodos = data.ler("periodos_fechados")
clientes = data.ler("clientes")
taxas = data.ler("taxas")

email = data.utilizador_atual()
hoje = data.hoje()
fecho = H.data_fecho(periodos)
agora_txt = lambda: data.agora().strftime("%Y-%m-%d %H:%M")  # noqa: E731

aprovaveis = membros[membros.apply(lambda m: sessao.pode_aprovar(u, m), axis=1)] \
    if not membros.empty else membros
ids_aprov = set(aprovaveis["id"]) if not aprovaveis.empty else set()
nomes = dict(zip(membros["id"], membros["nome"]))
enriq = H.enriquecer(registos, projetos, tarefas, membros, clientes, taxas)

separadores = ["Pendentes", "Estado das semanas"] + (["Fecho de períodos"] if u.admin else [])
abas = st.tabs(separadores)

# ==========================================================================
# Pendentes
# ==========================================================================
with abas[0]:
    pend = submissoes[
        (submissoes["estado"] == "Submetida") & (submissoes["membro_id"].isin(ids_aprov))
    ] if not submissoes.empty else submissoes

    if pend.empty:
        st.success("Não há semanas a aguardar aprovação.", icon="✅")
    else:
        pend = pend.sort_values(["semana", "membro_id"])
        st.caption(f"{len(pend)} semana(s) a aguardar aprovação.")

        for _, s in pend.iterrows():
            seg = s["semana"].date()
            fim = seg + timedelta(days=6)
            dele = enriq[
                (enriq["membro_id"] == s["membro_id"])
                & (enriq["data"] >= pd.Timestamp(seg)) & (enriq["data"] <= pd.Timestamp(fim))
            ] if not enriq.empty else enriq
            total = dele["horas"].sum() if not dele.empty else 0.0
            meta = float(membros.loc[membros["id"] == s["membro_id"], "horas_semana"].max() or 40)
            sinal = int(dele["sinalizado"].sum()) if not dele.empty else 0

            titulo = (
                f"{nomes.get(s['membro_id'], s['membro_id'])} — semana de {seg:%d/%m} a {fim:%d/%m/%Y}"
                f" — {total:.2f} h de {meta:.0f} h" + (f" — ⚠️ {sinal} sinalizado(s)" if sinal else "")
            )
            with st.expander(titulo):
                if dele.empty:
                    st.caption("Sem registos.")
                else:
                    por_dia = dele.groupby(dele["data"].dt.date)["horas"].sum()
                    excesso = por_dia[por_dia > LIMITE_HORAS_REGISTO]
                    if sinal or not excesso.empty:
                        st.warning(
                            f"Registos com mais de {LIMITE_HORAS_REGISTO} h: {sinal}. "
                            f"Dias acima de {LIMITE_HORAS_REGISTO} h: "
                            + (", ".join(f"{d:%d/%m}" for d in excesso.index) or "nenhum") + ".",
                            icon="⚠️",
                        )
                    cols = ["sinalizado", "data", "codigo", "tarefa", "disciplina", "hora_inicio",
                            "hora_fim", "horas", "descricao", "tags", "faturavel"]
                    st.dataframe(
                        dele[cols], hide_index=True, width="stretch",
                        column_config={
                            "sinalizado": st.column_config.CheckboxColumn("⚠️", width="small"),
                            "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                            "codigo": "Projeto", "tarefa": "Tarefa", "disciplina": "Disc.",
                            "hora_inicio": "Início", "hora_fim": "Fim",
                            "horas": st.column_config.NumberColumn("Horas", format="%.2f"),
                            "descricao": "Descrição", "tags": "Tags",
                            "faturavel": st.column_config.CheckboxColumn("Fat."),
                        },
                    )

                comentario = st.text_input("Comentário (obrigatório para devolver)", key=f"com_{s['id']}")
                b1, b2, _ = st.columns([1, 1, 4])
                if b1.button("✅ Aprovar", key=f"apr_{s['id']}", type="primary"):
                    data.atualizar(
                        "submissoes", s["id"],
                        {"estado": "Aprovada", "revisto_por": u.nome, "revisto_em": agora_txt(),
                         "comentario": comentario.strip()},
                        utilizador=email,
                    )
                    st.rerun()
                if b2.button("↩️ Devolver", key=f"dev_{s['id']}"):
                    if not comentario.strip():
                        st.error("Indica o motivo da devolução.")
                    else:
                        data.atualizar(
                            "submissoes", s["id"],
                            {"estado": "Devolvida", "revisto_por": u.nome, "revisto_em": agora_txt(),
                             "comentario": comentario.strip()},
                            utilizador=email,
                        )
                        st.rerun()

        st.divider()
        if st.button(f"Aprovar todas as {len(pend)} semanas sem registos sinalizados"):
            lote = {}
            for _, s in pend.iterrows():
                seg = s["semana"].date()
                dele = enriq[
                    (enriq["membro_id"] == s["membro_id"])
                    & (enriq["data"] >= pd.Timestamp(seg))
                    & (enriq["data"] <= pd.Timestamp(seg + timedelta(days=6)))
                ] if not enriq.empty else enriq
                if dele.empty or not dele["sinalizado"].any():
                    lote[s["id"]] = {"estado": "Aprovada", "revisto_por": u.nome, "revisto_em": agora_txt()}
            data.atualizar_lote("submissoes", lote, utilizador=email)
            st.toast(f"{len(lote)} semana(s) aprovada(s).", icon="✅")
            st.rerun()

# ==========================================================================
# Estado das semanas (visão geral e reabertura)
# ==========================================================================
with abas[1]:
    n = st.slider("Semanas a mostrar", 4, 16, 8)
    seg_atual = H.segunda(hoje)
    semanas = [seg_atual - timedelta(weeks=i) for i in range(n - 1, -1, -1)]
    alvo = aprovaveis if not aprovaveis.empty else membros.iloc[0:0]
    alvo = alvo[alvo["ativo"].astype(str).str.lower() != "não"] if not alvo.empty else alvo

    if alvo.empty:
        st.caption("Sem membros a cargo.")
    else:
        simbolo = {"Aprovada": "✅", "Submetida": "📨", "Devolvida": "↩️", "": "·"}
        linhas = []
        for _, m in alvo.iterrows():
            linha = {"Membro": m["nome"]}
            for s in semanas:
                est = H.estado_semana(submissoes, m["id"], s)
                tot = H.resumo_semana(registos, m["id"], s, hoje, m["horas_semana"])["total_min"] / 60
                linha[f"{s:%d/%m}"] = f"{simbolo.get(est, '·')} {tot:.1f}"
            linhas.append(linha)
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
        st.caption("✅ aprovada · 📨 submetida · ↩️ devolvida · «·» por submeter — seguido das horas registadas.")

        st.markdown("**Reabrir semana aprovada**")
        aprovadas = submissoes[
            (submissoes["estado"] == "Aprovada") & (submissoes["membro_id"].isin(set(alvo["id"])))
        ] if not submissoes.empty else submissoes
        if aprovadas.empty:
            st.caption("Sem semanas aprovadas.")
        else:
            aprovadas = aprovadas.sort_values("semana", ascending=False)
            opcoes = {
                r["id"]: f"{nomes.get(r['membro_id'], '?')} — {r['semana']:%d/%m/%Y}"
                for _, r in aprovadas.iterrows()
            }
            c1, c2, c3 = st.columns([2, 3, 1])
            sel = c1.selectbox("Semana", list(opcoes), format_func=lambda i: opcoes[i])
            motivo = c2.text_input("Motivo", key="motivo_reabrir")
            c3.write("")
            if c3.button("Reabrir", width="stretch"):
                seg_sel = aprovadas.loc[aprovadas["id"] == sel, "semana"].iloc[0].date()
                if fecho and seg_sel <= fecho:
                    st.error(f"A semana está dentro do período fechado até {fecho:%d/%m/%Y}.")
                elif not motivo.strip():
                    st.error("Indica o motivo.")
                else:
                    data.atualizar(
                        "submissoes", sel,
                        {"estado": "Devolvida", "revisto_por": u.nome, "revisto_em": agora_txt(),
                         "comentario": f"Reaberta: {motivo.strip()}"},
                        utilizador=email,
                    )
                    st.rerun()

# ==========================================================================
# Fecho de períodos (admin)
# ==========================================================================
if u.admin:
    with abas[2]:
        st.caption(
            "Fechar um período bloqueia todos os registos até à data indicada (inclusive), "
            "para todos os membros, independentemente do estado das semanas."
        )
        if fecho:
            st.info(f"Fechado até **{fecho:%d/%m/%Y}**.", icon="🔒")
        else:
            st.caption("Nenhum período fechado.")

        # Semanas por aprovar dentro do período a fechar
        with st.form("fechar"):
            c1, c2 = st.columns([1, 3])
            ate = c1.date_input(
                "Fechar até", value=(hoje.replace(day=1) - timedelta(days=1)), format="DD/MM/YYYY"
            )
            motivo = c2.text_input("Motivo", placeholder="Fecho mensal — faturação de agosto")
            if st.form_submit_button("🔒 Fechar período", type="primary"):
                if fecho and ate <= fecho:
                    st.error(f"Já está fechado até {fecho:%d/%m/%Y}.")
                else:
                    pendentes = submissoes[
                        (submissoes["estado"] == "Submetida") & (submissoes["semana"] <= pd.Timestamp(ate))
                    ] if not submissoes.empty else submissoes
                    data.inserir(
                        "periodos_fechados", {"data_fecho": ate, "motivo": motivo.strip()},
                        utilizador=email,
                    )
                    if not pendentes.empty:
                        st.warning(f"Atenção: {len(pendentes)} semana(s) submetida(s) ficaram por aprovar.")
                    st.rerun()

        if not periodos.empty:
            hist = periodos.sort_values("data_fecho", ascending=False)
            st.dataframe(
                hist[["data_fecho", "motivo", "atualizado_por", "atualizado_em"]],
                hide_index=True, width="stretch",
                column_config={
                    "data_fecho": st.column_config.DateColumn("Fechado até", format="DD/MM/YYYY"),
                    "motivo": "Motivo", "atualizado_por": "Por", "atualizado_em": "Em",
                },
            )
            if st.button("🔓 Reabrir o último fecho"):
                data.eliminar("periodos_fechados", hist.iloc[0]["id"])
                st.rerun()
