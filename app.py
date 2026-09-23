"""Ponto de entrada da aplicação de gestão de projetos.

Executar localmente:
    streamlit run app.py
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from datetime import timedelta

from lib import data, sessao
from lib import horas as H
from lib.config import APP_ICON, APP_NOME, DIAS_SEMANA, DISCIPLINAS

st.set_page_config(
    page_title=APP_NOME,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------
# Barra lateral partilhada
# --------------------------------------------------------------------------
def barra_lateral() -> None:
    with st.sidebar:
        st.markdown(f"### {APP_ICON} {APP_NOME}")
        st.caption(f"Sessão: {data.utilizador_atual()}")
        st.divider()

        if data.ligacao_ativa():
            st.success(data.estado_ligacao(), icon="🟢")
        else:
            st.error(data.estado_ligacao(), icon="🔴")

        if st.button("Atualizar dados", width="stretch"):
            data.limpar_cache()
            st.rerun()

        with st.expander("Manutenção"):
            st.caption(
                "Cria abas e colunas em falta na folha de cálculo. "
                "Correr após qualquer alteração ao esquema."
            )
            if st.button("Verificar esquema", width="stretch"):
                if not data.ligacao_ativa():
                    st.warning("Sem ligação configurada.")
                else:
                    with st.spinner("A verificar..."):
                        acoes = data.garantir_esquema()
                    if acoes:
                        for a in acoes:
                            st.write(f"• {a}")
                    else:
                        st.write("Esquema já conforme.")
                    data.limpar_cache()


# --------------------------------------------------------------------------
# Instruções quando não há ligação
# --------------------------------------------------------------------------
def ecra_configuracao() -> None:
    st.title(f"{APP_ICON} {APP_NOME}")
    st.warning("A aplicação ainda não está ligada ao Google Sheets.", icon="⚠️")

    st.markdown(
        """
Para pôr isto a funcionar são precisos dois blocos nos *secrets* do Streamlit
(**Settings → Secrets** na app publicada, ou `.streamlit/secrets.toml` em local):

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "gestao-projetos@....iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"

[sheets]
spreadsheet_id = "1AbC...XyZ"
```

O passo a passo completo de criação da conta de serviço está no `README.md`
do repositório.
"""
    )


# --------------------------------------------------------------------------
# Painel pessoal de horas
# --------------------------------------------------------------------------
def painel_horas(membros: pd.DataFrame) -> None:
    u = sessao.utilizador(membros)
    if u is None:
        if not membros.empty:
            st.caption(
                f"O email {data.utilizador_atual()} não está associado a nenhum membro: "
                "o registo de horas fica indisponível até um administrador o acrescentar."
            )
        return
    sessao.cartao_lateral(u)

    registos = data.ler("registos")
    submissoes = data.ler("submissoes")
    hoje = data.hoje()
    seg = H.segunda(hoje)
    r = H.resumo_semana(registos, u.id, seg, hoje, u.horas_semana)

    st.subheader(f"As minhas horas — semana de {seg:%d/%m}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registadas", H.fmt_horas(r["total_min"]))
    c2.metric("Meta", H.fmt_horas(r["meta_min"]))
    c3.metric("Estado", H.estado_semana(submissoes, u.id, seg) or "Aberta")
    ativo = (
        registos[(registos["membro_id"] == u.id) & (registos["estado"] == "Em curso")]
        if not registos.empty else registos
    )
    c4.metric("Temporizador", f"desde {ativo.iloc[0]['hora_inicio']}" if not ativo.empty else "parado")
    if r["meta_min"]:
        st.progress(min(r["total_min"] / r["meta_min"], 1.0))

    avisos = []
    if r["dias_em_falta"]:
        avisos.append(
            "Dias abaixo da meta: "
            + ", ".join(f"{DIAS_SEMANA[d.weekday()]} {d:%d/%m}" for d in r["dias_em_falta"])
        )
    anterior = seg - timedelta(days=7)
    est_ant = H.estado_semana(submissoes, u.id, anterior)
    if est_ant in ("", "Devolvida"):
        avisos.append(
            f"Semana de {anterior:%d/%m} "
            + ("devolvida — corrige e volta a submeter" if est_ant else "ainda por submeter")
        )
    for a in avisos:
        st.warning(a, icon="🕒")

    if u.gestor:
        visiveis = set(membros["id"])
        pend = submissoes[
            (submissoes["estado"] == "Submetida")
            & submissoes["membro_id"].map(
                lambda i: i in visiveis and sessao.pode_aprovar(u, membros[membros["id"] == i].iloc[0])
            )
        ] if not submissoes.empty else submissoes
        if not pend.empty:
            st.info(f"{len(pend)} semana(s) a aguardar a tua aprovação em **Aprovações**.", icon="📨")

        orc = H.orcamento_projetos(
            H.enriquecer(registos, data.ler("projetos"), data.ler("tarefas"), membros,
                         data.ler("clientes"), data.ler("taxas")),
            data.ler("projetos"),
        )
        alerta = orc[orc["alerta"].isin(["Atenção", "Excedido"])]
        for _, p in alerta.iterrows():
            st.warning(
                f"Orçamento {p['codigo'] or p['projeto']}: {p['registadas']:.0f} h de "
                f"{p['orcadas']:.0f} h ({p['consumo']:.0%}).",
                icon="🛑" if p["alerta"] == "Excedido" else "⚠️",
            )
    st.divider()


# --------------------------------------------------------------------------
# Painel principal
# --------------------------------------------------------------------------
def painel() -> None:
    projetos = data.ler("projetos")
    tarefas = data.ler("tarefas")
    equipas = data.ler("equipas")
    membros = data.ler("membros")

    st.title(f"{APP_ICON} {APP_NOME}")

    painel_horas(membros)

    if projetos.empty and tarefas.empty:
        st.info(
            "Ainda não há dados. Começa por criar um projeto no separador "
            "**Projetos**, e depois uma equipa em **Equipas**.",
            icon="👋",
        )
        return

    hoje = pd.Timestamp(date.today())
    ativas = tarefas[tarefas["estado"] != "Concluída"] if not tarefas.empty else tarefas

    if not tarefas.empty:
        atrasadas = tarefas[
            (tarefas["data_fim"] < hoje) & (pd.to_numeric(tarefas["progresso"], errors="coerce").fillna(0) < 100)
        ]
        progresso_medio = pd.to_numeric(tarefas["progresso"], errors="coerce").fillna(0).mean()
    else:
        atrasadas = tarefas
        progresso_medio = 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Projetos", len(projetos))
    c2.metric("Tarefas", len(tarefas))
    c3.metric("Em curso", len(ativas))
    c4.metric("Progresso médio", f"{progresso_medio:.0f}%")
    c5.metric("Em atraso", len(atrasadas), delta=None if len(atrasadas) == 0 else "atenção",
              delta_color="inverse")

    st.divider()

    esq, dir_ = st.columns([3, 2])

    with esq:
        st.subheader("Progresso por projeto")
        from lib.gantt import resumo_por_projeto

        resumo = resumo_por_projeto(tarefas, projetos)
        if resumo.empty:
            st.caption("Sem tarefas com datas definidas.")
        else:
            st.dataframe(
                resumo,
                hide_index=True,
                width="stretch",
                column_config={
                    "projeto": st.column_config.TextColumn("Projeto"),
                    "inicio": st.column_config.DateColumn("Início", format="DD/MM/YYYY"),
                    "fim": st.column_config.DateColumn("Fim", format="DD/MM/YYYY"),
                    "tarefas": st.column_config.NumberColumn("Tarefas"),
                    "progresso": st.column_config.ProgressColumn(
                        "Progresso", min_value=0, max_value=100, format="%d%%"
                    ),
                },
            )

    with dir_:
        st.subheader("Carga por disciplina")
        if tarefas.empty:
            st.caption("Sem tarefas registadas.")
        else:
            contagem = tarefas["disciplina"].value_counts()
            barras = pd.DataFrame(
                {
                    "Disciplina": [
                        f"{d} — {DISCIPLINAS.get(d, {}).get('desc', '')}" for d in contagem.index
                    ],
                    "Tarefas": contagem.values,
                }
            )
            st.bar_chart(barras, x="Disciplina", y="Tarefas", horizontal=True, height=300)

    if not atrasadas.empty:
        st.divider()
        st.subheader("Tarefas em atraso")
        nomes_proj = dict(zip(projetos["id"], projetos["nome"]))
        nomes_memb = dict(zip(membros["id"], membros["nome"])) if not membros.empty else {}
        vista = atrasadas.assign(
            Projeto=atrasadas["projeto_id"].map(nomes_proj),
            Responsável=atrasadas["responsavel_id"].map(nomes_memb).fillna("(por atribuir)"),
            Atraso=(hoje - atrasadas["data_fim"]).dt.days,
        )[["Projeto", "nome", "disciplina", "Responsável", "data_fim", "progresso", "Atraso"]]

        st.dataframe(
            vista,
            hide_index=True,
            width="stretch",
            column_config={
                "nome": "Tarefa",
                "disciplina": "Disc.",
                "data_fim": st.column_config.DateColumn("Prazo", format="DD/MM/YYYY"),
                "progresso": st.column_config.ProgressColumn(
                    "Progresso", min_value=0, max_value=100, format="%d%%"
                ),
                "Atraso": st.column_config.NumberColumn("Dias", format="%d d"),
            },
        )


# --------------------------------------------------------------------------
barra_lateral()

if data.ligacao_ativa():
    painel()
else:
    ecra_configuracao()
