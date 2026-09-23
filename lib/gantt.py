"""Construção do cronograma (Gantt) em Plotly.

A função pública é `construir_gantt`. Recebe já os dados filtrados e devolve
uma figura pronta a passar ao `st.plotly_chart`.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px

from lib.config import CORES_DISCIPLINA

ALTURA_LINHA = 30
ALTURA_MINIMA = 320

CONFIG_ESCALA = {
    "dia": {"dtick": 86400000.0, "tickformat": "%d %b", "margem": 2},
    "semana": {"dtick": 604800000.0, "tickformat": "%d %b", "margem": 7},
    "mês": {"dtick": "M1", "tickformat": "%b %Y", "margem": 21},
}


def _preparar(tarefas: pd.DataFrame, projetos: pd.DataFrame, membros: pd.DataFrame) -> pd.DataFrame:
    """Junta nomes de projeto e responsável e calcula campos derivados."""
    df = tarefas.copy()
    df = df.dropna(subset=["data_inicio", "data_fim"])
    if df.empty:
        return df

    # Uma tarefa de um só dia precisa de largura visível
    iguais = df["data_fim"] <= df["data_inicio"]
    df.loc[iguais, "data_fim"] = df.loc[iguais, "data_inicio"] + pd.Timedelta(days=1)

    nomes_proj = dict(zip(projetos["id"], projetos["nome"])) if not projetos.empty else {}
    nomes_memb = dict(zip(membros["id"], membros["nome"])) if not membros.empty else {}

    df["projeto"] = df["projeto_id"].map(nomes_proj).fillna("(sem projeto)")
    df["responsavel"] = df["responsavel_id"].map(nomes_memb).fillna("(por atribuir)")
    df["progresso"] = pd.to_numeric(df["progresso"], errors="coerce").fillna(0)

    hoje = pd.Timestamp(date.today())
    df["em_atraso"] = (df["data_fim"] < hoje) & (df["progresso"] < 100)

    # Rótulo do eixo Y: projeto + tarefa, truncado para não esmagar o gráfico
    def _rotulo(linha):
        nome = linha["nome"] if len(str(linha["nome"])) <= 45 else str(linha["nome"])[:42] + "..."
        return f"{linha['projeto']} · {nome}"

    df["rotulo"] = df.apply(_rotulo, axis=1)

    # Desambiguar rótulos repetidos (o eixo Y do Plotly agrega categorias iguais)
    ocorrencia = df.groupby("rotulo").cumcount()
    df["rotulo"] = [
        r if n == 0 else f"{r} ({n + 1})" for r, n in zip(df["rotulo"], ocorrencia)
    ]

    df["duracao"] = (df["data_fim"] - df["data_inicio"]).dt.days
    df["fim_progresso"] = df["data_inicio"] + pd.to_timedelta(
        df["duracao"] * df["progresso"] / 100.0, unit="D"
    )

    return df.sort_values(["projeto", "data_inicio", "nome"])


def construir_gantt(
    tarefas: pd.DataFrame,
    projetos: pd.DataFrame,
    membros: pd.DataFrame,
    escala: str = "semana",
    mostrar_progresso: bool = True,
    marcar_atrasos: bool = True,
):
    """Devolve a figura Plotly do cronograma, ou None se não houver dados."""
    df = _preparar(tarefas, projetos, membros)
    if df.empty:
        return None

    ordem = list(df["rotulo"])

    fig = px.timeline(
        df,
        x_start="data_inicio",
        x_end="data_fim",
        y="rotulo",
        color="disciplina",
        color_discrete_map=CORES_DISCIPLINA,
        custom_data=["projeto", "nome", "responsavel", "progresso", "estado", "fase"],
    )

    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>"
            "Projeto: %{customdata[0]}<br>"
            "Responsável: %{customdata[2]}<br>"
            "Fase: %{customdata[5]}<br>"
            "Estado: %{customdata[4]}<br>"
            "Progresso: %{customdata[3]:.0f}%<br>"
            "Início: %{base|%d/%m/%Y}<extra></extra>"
        ),
        marker_line_width=0,
        opacity=0.55,
    )

    # Sobreposição escura proporcional ao progresso
    if mostrar_progresso:
        feitas = df[df["progresso"] > 0]
        if not feitas.empty:
            fig_prog = px.timeline(
                feitas, x_start="data_inicio", x_end="fim_progresso", y="rotulo",
                color="disciplina", color_discrete_map=CORES_DISCIPLINA,
            )
            for traco in fig_prog.data:
                traco.showlegend = False
                traco.opacity = 1.0
                traco.width = 0.45
                traco.hoverinfo = "skip"
                fig.add_trace(traco)

    # Contorno vermelho nas tarefas em atraso
    if marcar_atrasos:
        atrasadas = df[df["em_atraso"]]
        if not atrasadas.empty:
            fig_atr = px.timeline(
                atrasadas, x_start="data_inicio", x_end="data_fim", y="rotulo"
            )
            for traco in fig_atr.data:
                traco.showlegend = False
                traco.marker.color = "rgba(0,0,0,0)"
                traco.marker.line.color = "#DC2626"
                traco.marker.line.width = 2
                traco.hoverinfo = "skip"
                fig.add_trace(traco)

    cfg = CONFIG_ESCALA.get(escala, CONFIG_ESCALA["semana"])
    margem = timedelta(days=cfg["margem"])
    inicio = df["data_inicio"].min() - margem
    fim = df["data_fim"].max() + margem

    # Linha do dia de hoje
    hoje = pd.Timestamp(date.today())
    if inicio <= hoje <= fim:
        fig.add_shape(
            type="line", x0=hoje, x1=hoje, y0=0, y1=1, yref="paper",
            line=dict(color="#DC2626", width=2, dash="dot"),
        )
        fig.add_annotation(
            x=hoje, y=1.02, yref="paper", text="hoje", showarrow=False,
            font=dict(size=11, color="#DC2626"),
        )

    fig.update_yaxes(
        autorange="reversed",
        categoryorder="array",
        categoryarray=ordem,
        title=None,
        tickfont=dict(size=11),
    )
    fig.update_xaxes(
        range=[inicio, fim],
        dtick=cfg["dtick"],
        tickformat=cfg["tickformat"],
        side="top",
        showgrid=True,
        gridcolor="rgba(0,0,0,0.08)",
        title=None,
    )
    fig.update_layout(
        height=max(ALTURA_MINIMA, ALTURA_LINHA * len(df) + 140),
        margin=dict(l=10, r=20, t=70, b=30),
        barmode="overlay",
        bargap=0.35,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.06, xanchor="left", x=0,
            title=None, font=dict(size=11),
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(font_size=12),
    )

    return fig


def resumo_por_projeto(tarefas: pd.DataFrame, projetos: pd.DataFrame) -> pd.DataFrame:
    """Tabela agregada: datas extremas e progresso médio ponderado por duração."""
    if tarefas.empty or projetos.empty:
        return pd.DataFrame()

    df = tarefas.dropna(subset=["data_inicio", "data_fim"]).copy()
    if df.empty:
        return pd.DataFrame()

    df["dias"] = (df["data_fim"] - df["data_inicio"]).dt.days.clip(lower=1)
    df["peso"] = df["dias"] * pd.to_numeric(df["progresso"], errors="coerce").fillna(0)

    agregado = df.groupby("projeto_id").agg(
        inicio=("data_inicio", "min"),
        fim=("data_fim", "max"),
        tarefas=("id", "count"),
        dias=("dias", "sum"),
        peso=("peso", "sum"),
    )
    agregado["progresso"] = (agregado["peso"] / agregado["dias"]).round(0)
    agregado = agregado.drop(columns=["peso", "dias"])

    nomes = dict(zip(projetos["id"], projetos["nome"]))
    agregado.insert(0, "projeto", agregado.index.map(nomes))
    return agregado.reset_index(drop=True)
