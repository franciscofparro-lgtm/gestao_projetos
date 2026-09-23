"""Exportação de relatórios de horas para Excel e CSV.

Formato-padrão do gabinete: Arial; título 14 pt negrito sobre #16365C;
cabeçalhos 11 pt negrito sobre #16365C, texto branco, limite médio;
linhas alternadas #FFFFFF / #F2F2F2 com limite fino; totais sobre #BCC8E0.
Os totais são fórmulas SUM, para continuarem certos se o ficheiro for editado.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

AZUL = "16365C"
AZUL_CLARO = "BCC8E0"
CINZA = "F2F2F2"
BRANCO = "FFFFFF"

_FINO = Side(style="thin", color="A6A6A6")
_MEDIO = Side(style="medium", color="000000")
BORDA_FINA = Border(left=_FINO, right=_FINO, top=_FINO, bottom=_FINO)
BORDA_MEDIA = Border(left=_MEDIO, right=_MEDIO, top=_MEDIO, bottom=_MEDIO)

FMT_HORAS = "0.00"
FMT_EURO = '#,##0.00 "€"'
FMT_DATA = "DD/MM/YYYY"
FMT_PCT = "0%"


def _fill(cor: str) -> PatternFill:
    # Instanciado por célula: objetos de estilo partilhados por referência
    # podem propagar alterações de forma inesperada.
    return PatternFill("solid", start_color=cor, end_color=cor)


def _titulo(ws, texto: str, linhas_info: list[str], n_colunas: int) -> int:
    """Escreve título e linhas de contexto. Devolve a próxima linha livre."""
    n_colunas = max(n_colunas, 2)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_colunas)
    c = ws.cell(row=1, column=1, value=texto)
    c.font = Font(name="Arial", size=14, bold=True, color=BRANCO)
    c.fill = _fill(AZUL)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    for col in range(1, n_colunas + 1):
        ws.cell(row=1, column=col).border = BORDA_MEDIA
        ws.cell(row=1, column=col).fill = _fill(AZUL)
    ws.row_dimensions[1].height = 28

    linha = 2
    for info in linhas_info:
        ws.cell(row=linha, column=1, value=info).font = Font(name="Arial", size=11, color="404040")
        ws.row_dimensions[linha].height = 16.5
        linha += 1
    return linha + 1


def _tabela(
    ws,
    df: pd.DataFrame,
    linha: int,
    formatos: dict[str, str] | None = None,
    totais: list[str] | None = None,
    rotulo_total: str = "Total",
) -> int:
    """Escreve uma tabela com cabeçalho, linhas alternadas e totais. Devolve a linha seguinte."""
    formatos = formatos or {}
    totais = totais or []
    colunas = list(df.columns)

    for j, nome in enumerate(colunas, start=1):
        c = ws.cell(row=linha, column=j, value=nome)
        c.font = Font(name="Arial", size=11, bold=True, color=BRANCO)
        c.fill = _fill(AZUL)
        c.border = BORDA_MEDIA
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[linha].height = 28
    inicio = linha + 1

    for i, (_, reg) in enumerate(df.iterrows()):
        r = inicio + i
        cor = BRANCO if i % 2 == 0 else CINZA
        for j, nome in enumerate(colunas, start=1):
            v = reg[nome]
            if isinstance(v, pd.Timestamp):
                v = None if pd.isna(v) else v.to_pydatetime()
            elif v is not None and not isinstance(v, (str, date, datetime)) and pd.isna(v):
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            c = ws.cell(row=r, column=j, value=v)
            c.font = Font(name="Arial", size=11)
            c.fill = _fill(cor)
            c.border = BORDA_FINA
            numerico = isinstance(v, (int, float)) and not isinstance(v, bool)
            c.alignment = Alignment(
                horizontal="right" if numerico or isinstance(v, (date, datetime)) else "left",
                vertical="center",
            )
            if nome in formatos:
                c.number_format = formatos[nome]
            elif isinstance(v, (date, datetime)):
                c.number_format = FMT_DATA
        ws.row_dimensions[r].height = 16.5

    fim = inicio + len(df) - 1
    proxima = fim + 1
    if totais and len(df):
        r = proxima
        for j, nome in enumerate(colunas, start=1):
            c = ws.cell(row=r, column=j)
            c.font = Font(name="Arial", size=11, bold=True)
            c.fill = _fill(AZUL_CLARO)
            c.border = BORDA_MEDIA
            if j == 1:
                c.value = rotulo_total
                c.alignment = Alignment(horizontal="left", vertical="center")
            elif nome in totais:
                letra = get_column_letter(j)
                c.value = f"=SUM({letra}{inicio}:{letra}{fim})"
                c.number_format = formatos.get(nome, FMT_HORAS)
                c.alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[r].height = 18
        proxima = r + 1

    # Larguras aproximadas pelo conteúdo
    for j, nome in enumerate(colunas, start=1):
        amostra = [len(str(nome))] + [len(str(x)) for x in df[nome].head(200).tolist()]
        ws.column_dimensions[get_column_letter(j)].width = min(max(amostra) + 3, 55)

    return proxima + 1


def excel_relatorio(
    titulo: str,
    info: list[str],
    resumo: pd.DataFrame,
    detalhado: pd.DataFrame,
    semanal: pd.DataFrame | None = None,
    formatos: dict[str, str] | None = None,
) -> bytes:
    """Livro com as folhas Resumo, Detalhado e (opcional) Semanal."""
    formatos = formatos or {}
    wb = Workbook()

    def _totais(df):
        return [c for c in df.columns if formatos.get(c) in (FMT_HORAS, FMT_EURO)]

    ws = wb.active
    ws.title = "Resumo"
    linha = _titulo(ws, titulo, info, len(resumo.columns))
    _tabela(ws, resumo, linha, formatos, _totais(resumo))
    ws.freeze_panes = ws.cell(row=linha + 1, column=1)

    ws2 = wb.create_sheet("Detalhado")
    linha = _titulo(ws2, f"{titulo} — detalhado", info, len(detalhado.columns))
    _tabela(ws2, detalhado, linha, formatos, _totais(detalhado))
    ws2.freeze_panes = ws2.cell(row=linha + 1, column=1)
    ws2.auto_filter.ref = (
        f"A{linha}:{get_column_letter(len(detalhado.columns))}{linha + max(len(detalhado), 1)}"
    )

    if semanal is not None and not semanal.empty:
        ws3 = wb.create_sheet("Semanal")
        linha = _titulo(ws3, f"{titulo} — semanal", info, len(semanal.columns))
        fmts = {c: FMT_HORAS for c in semanal.columns[1:]}
        _tabela(ws3, semanal, linha, fmts, list(semanal.columns[1:]))
        ws3.freeze_panes = ws3.cell(row=linha + 1, column=2)

    for folha in wb.worksheets:
        folha.sheet_view.showGridLines = False
        folha.page_setup.orientation = "landscape"
        folha.page_setup.paperSize = folha.PAPERSIZE_A4
        folha.page_setup.fitToWidth = 1
        folha.page_setup.fitToHeight = 0
        folha.sheet_properties.pageSetUpPr.fitToPage = True

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_pt(df: pd.DataFrame) -> bytes:
    """CSV para Excel em português: separador ';', vírgula decimal, UTF-8 com BOM."""
    saida = df.copy()
    for c in saida.columns:
        if pd.api.types.is_datetime64_any_dtype(saida[c]):
            saida[c] = saida[c].dt.strftime("%d/%m/%Y")
    return saida.to_csv(sep=";", decimal=",", index=False, float_format="%.2f").encode("utf-8-sig")
