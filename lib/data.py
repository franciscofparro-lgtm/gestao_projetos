"""Camada de acesso a dados.

Este é o ÚNICO módulo que comunica com o Google Sheets. Nenhuma página deve
importar gspread diretamente. Se um dia o backend mudar (Postgres, SQLite,
SharePoint), só este ficheiro é reescrito — a assinatura das funções públicas
mantém-se.

Funções públicas:
    ligacao_ativa()                  -> bool
    estado_ligacao()                 -> str
    ler(tabela)                      -> DataFrame
    inserir(tabela, registo)         -> str (id criado)
    atualizar(tabela, id, alteracoes)
    eliminar(tabela, id)
    inserir_lote(tabela, registos)   -> list[str]
    atualizar_lote(tabela, {id: alteracoes})
    eliminar_lote(tabela, ids)
    novo_id(prefixo)                 -> str
    limpar_cache()
    garantir_esquema()
"""

from __future__ import annotations

import uuid
from datetime import datetime, date

import pandas as pd
import streamlit as st

from lib.config import SCHEMAS, COLUNAS_DATA, COLUNAS_NUM, COLUNAS_NUM_LIVRE, CACHE_TTL, FUSO

try:
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo(FUSO)
except Exception:  # pragma: no cover
    _TZ = None


def agora() -> datetime:
    """Data e hora locais (Europe/Lisbon), sem informação de fuso."""
    if _TZ is None:
        return datetime.now()
    return datetime.now(_TZ).replace(tzinfo=None)


def hoje() -> date:
    """Data local (Europe/Lisbon). O servidor do Streamlit Cloud corre em UTC."""
    return agora().date()

try:
    import gspread
    from google.oauth2.service_account import Credentials

    _GSPREAD_DISPONIVEL = True
except ImportError:  # pragma: no cover
    _GSPREAD_DISPONIVEL = False

# Escrita em modo RAW: os valores ficam na folha exatamente como enviados.
# Com USER_ENTERED, numa folha com localização portuguesa, "1.5" podia ser
# interpretado como data (1 de maio) e "09:30" como fração de dia.
_MODO_ESCRITA = "RAW"

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


# ==========================================================================
# Ligação
# ==========================================================================
def ligacao_ativa() -> bool:
    """Indica se há credenciais configuradas e a biblioteca está instalada."""
    if not _GSPREAD_DISPONIVEL:
        return False
    return "gcp_service_account" in st.secrets and "sheets" in st.secrets


def estado_ligacao() -> str:
    """Mensagem legível sobre o estado da ligação, para mostrar na barra lateral."""
    if not _GSPREAD_DISPONIVEL:
        return "Biblioteca gspread não instalada"
    if "gcp_service_account" not in st.secrets:
        return "Credenciais da conta de serviço em falta nos secrets"
    if "sheets" not in st.secrets:
        return "Identificador da folha em falta nos secrets"
    return "Ligado ao Google Sheets"


@st.cache_resource(show_spinner=False)
def _cliente():
    """Cliente gspread autenticado. Criado uma vez por sessão do servidor."""
    info = dict(st.secrets["gcp_service_account"])
    credenciais = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(credenciais)


@st.cache_resource(show_spinner=False)
def _folha():
    """Objeto Spreadsheet. Aceita id ou URL completo nos secrets."""
    cfg = st.secrets["sheets"]
    cliente = _cliente()
    if "spreadsheet_id" in cfg:
        return cliente.open_by_key(cfg["spreadsheet_id"])
    return cliente.open_by_url(cfg["spreadsheet_url"])


def _aba(tabela: str):
    """Devolve a worksheet, criando-a com cabeçalhos se ainda não existir."""
    livro = _folha()
    try:
        return livro.worksheet(tabela)
    except gspread.WorksheetNotFound:
        aba = livro.add_worksheet(title=tabela, rows=200, cols=max(len(SCHEMAS[tabela]), 12))
        aba.update([SCHEMAS[tabela]], "A1")
        aba.freeze(rows=1)
        return aba


def garantir_esquema() -> list[str]:
    """Cria as abas em falta e acrescenta colunas novas do esquema.

    Devolve a lista de ações executadas, para mostrar ao utilizador.
    """
    acoes: list[str] = []
    for tabela, colunas in SCHEMAS.items():
        aba = _aba(tabela)
        cabecalho = aba.row_values(1)
        if not cabecalho:
            aba.update([colunas], "A1")
            acoes.append(f"Cabeçalho criado em «{tabela}»")
            continue
        em_falta = [c for c in colunas if c not in cabecalho]
        if em_falta:
            novo = cabecalho + em_falta
            aba.update([novo], "A1")
            acoes.append(f"Colunas acrescentadas a «{tabela}»: {', '.join(em_falta)}")
    return acoes


# ==========================================================================
# Leitura
# ==========================================================================
@st.cache_data(ttl=CACHE_TTL, show_spinner="A carregar dados...")
def _ler_bruto(tabela: str) -> list[dict]:
    # numericise_ignore=["all"]: tudo chega como texto e a conversão de tipos
    # é feita em ler(). Evita que ids, NIF ou horas sejam alterados.
    return _aba(tabela).get_all_records(numericise_ignore=["all"])


def _data(serie: pd.Series) -> pd.Series:
    """ISO (AAAA-MM-DD) primeiro; se falhar, DD/MM/AAAA (formato PT do Sheets)."""
    texto = serie.astype(str).str.strip().str[:10]
    iso = pd.to_datetime(texto, format="%Y-%m-%d", errors="coerce")
    pt = pd.to_datetime(texto, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(pt)


def _numero(serie: pd.Series) -> pd.Series:
    """Converte para número aceitando vírgula decimal (valores escritos à mão no Sheets)."""
    limpa = serie.astype(str).str.strip().str.replace(",", ".", regex=False)
    return pd.to_numeric(limpa, errors="coerce").fillna(0)


def ler(tabela: str) -> pd.DataFrame:
    """Lê uma tabela e devolve um DataFrame com tipos já convertidos."""
    colunas = SCHEMAS[tabela]

    if not ligacao_ativa():
        return pd.DataFrame(columns=colunas)

    try:
        registos = _ler_bruto(tabela)
    except Exception as erro:  # noqa: BLE001
        st.error(f"Falha ao ler «{tabela}»: {erro}")
        return pd.DataFrame(columns=colunas)

    df = pd.DataFrame(registos)

    # Garante que todas as colunas do esquema existem, mesmo que vazias
    for col in colunas:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[colunas]

    for col in COLUNAS_DATA:
        if col in df.columns:
            df[col] = _data(df[col])

    for col in COLUNAS_NUM:
        if col in df.columns:
            df[col] = _numero(df[col]).clip(0, 100)

    for col in COLUNAS_NUM_LIVRE:
        if col in df.columns:
            df[col] = _numero(df[col]).clip(lower=0)

    # Identificadores e texto: sempre str, nunca NaN nem números convertidos
    texto = [c for c in colunas if c not in COLUNAS_DATA | COLUNAS_NUM | COLUNAS_NUM_LIVRE]
    for col in texto:
        df[col] = df[col].apply(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA else str(v))

    return df


# ==========================================================================
# Escrita
# ==========================================================================
def novo_id(prefixo: str) -> str:
    """Identificador curto e legível, ex.: 'TAR-3f9a2c'."""
    return f"{prefixo}-{uuid.uuid4().hex[:6]}"


def _serializar(valor):
    if valor is None or valor is pd.NA:
        return ""
    if isinstance(valor, float) and pd.isna(valor):
        return ""
    if valor is pd.NaT:
        return ""
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


def _carimbo(registo: dict, utilizador: str | None) -> dict:
    registo = dict(registo)
    registo["atualizado_por"] = utilizador or "desconhecido"
    registo["atualizado_em"] = agora().strftime("%Y-%m-%d %H:%M")
    return registo


def limpar_cache() -> None:
    """Invalida a cache de leitura. Chamar após qualquer escrita."""
    _ler_bruto.clear()


def inserir(tabela: str, registo: dict, utilizador: str | None = None) -> str:
    """Acrescenta uma linha. Devolve o id atribuído."""
    colunas = SCHEMAS[tabela]
    registo = _carimbo(registo, utilizador)
    if not registo.get("id"):
        registo["id"] = novo_id(tabela[:3].upper())

    linha = [_serializar(registo.get(c)) for c in colunas]
    _aba(tabela).append_row(linha, value_input_option=_MODO_ESCRITA)
    limpar_cache()
    return registo["id"]


def _indice_linha(tabela: str, id_registo: str) -> int | None:
    """Número da linha na folha (1-indexado) para um dado id, ou None."""
    ids = _aba(tabela).col_values(1)
    try:
        return ids.index(id_registo) + 1
    except ValueError:
        return None


def atualizar(tabela: str, id_registo: str, alteracoes: dict, utilizador: str | None = None) -> bool:
    """Atualiza os campos indicados de um registo existente."""
    colunas = SCHEMAS[tabela]
    aba = _aba(tabela)
    linha = _indice_linha(tabela, id_registo)
    if linha is None:
        st.error(f"Registo {id_registo} não encontrado em «{tabela}».")
        return False

    atuais = aba.row_values(linha)
    atuais += [""] * (len(colunas) - len(atuais))
    mapa = dict(zip(colunas, atuais))
    mapa.update(_carimbo(alteracoes, utilizador))
    mapa["id"] = id_registo

    nova = [_serializar(mapa.get(c)) for c in colunas]
    inicio = gspread.utils.rowcol_to_a1(linha, 1)
    fim = gspread.utils.rowcol_to_a1(linha, len(colunas))
    aba.update([nova], f"{inicio}:{fim}", value_input_option=_MODO_ESCRITA)
    limpar_cache()
    return True


def eliminar(tabela: str, id_registo: str) -> bool:
    """Remove uma linha definitivamente."""
    aba = _aba(tabela)
    linha = _indice_linha(tabela, id_registo)
    if linha is None:
        return False
    aba.delete_rows(linha)
    limpar_cache()
    return True


# ==========================================================================
# Escrita em lote (uma única chamada à API por operação)
# ==========================================================================
def inserir_lote(tabela: str, registos: list[dict], utilizador: str | None = None) -> list[str]:
    """Acrescenta várias linhas numa só chamada. Devolve os ids atribuídos."""
    if not registos:
        return []
    colunas = SCHEMAS[tabela]
    linhas, ids = [], []
    for reg in registos:
        reg = _carimbo(reg, utilizador)
        if not reg.get("id"):
            reg["id"] = novo_id(tabela[:3].upper())
        ids.append(reg["id"])
        linhas.append([_serializar(reg.get(c)) for c in colunas])
    _aba(tabela).append_rows(linhas, value_input_option=_MODO_ESCRITA)
    limpar_cache()
    return ids


def atualizar_lote(tabela: str, alteracoes: dict[str, dict], utilizador: str | None = None) -> list[str]:
    """Atualiza vários registos numa só chamada. Devolve os ids não encontrados."""
    if not alteracoes:
        return []
    colunas = SCHEMAS[tabela]
    aba = _aba(tabela)
    valores = aba.get_all_values()
    cabecalho = valores[0] if valores else colunas
    posicao = {row[0]: i + 1 for i, row in enumerate(valores) if row}

    pedidos, em_falta = [], []
    for id_registo, alt in alteracoes.items():
        linha = posicao.get(id_registo)
        if linha is None or linha == 1:
            em_falta.append(id_registo)
            continue
        atuais = valores[linha - 1] + [""] * (len(cabecalho) - len(valores[linha - 1]))
        mapa = dict(zip(cabecalho, atuais))
        mapa.update(_carimbo(alt, utilizador))
        mapa["id"] = id_registo
        nova = [_serializar(mapa.get(c)) for c in colunas]
        inicio = gspread.utils.rowcol_to_a1(linha, 1)
        fim = gspread.utils.rowcol_to_a1(linha, len(colunas))
        pedidos.append({"range": f"{inicio}:{fim}", "values": [nova]})

    if pedidos:
        aba.batch_update(pedidos, value_input_option=_MODO_ESCRITA)
        limpar_cache()
    return em_falta


def eliminar_lote(tabela: str, ids: list[str]) -> int:
    """Remove várias linhas numa só chamada. Devolve o número removido."""
    if not ids:
        return 0
    aba = _aba(tabela)
    todos = aba.col_values(1)
    alvo = set(ids)
    linhas = sorted((i for i, v in enumerate(todos) if v in alvo and i > 0), reverse=True)
    if not linhas:
        return 0
    # Apagar de baixo para cima para os índices não deslizarem
    pedidos = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": aba.id,
                    "dimension": "ROWS",
                    "startIndex": i,
                    "endIndex": i + 1,
                }
            }
        }
        for i in linhas
    ]
    _folha().batch_update({"requests": pedidos})
    limpar_cache()
    return len(linhas)


# ==========================================================================
# Auxiliares de conveniência
# ==========================================================================
def mapa_nomes(tabela: str, coluna: str = "nome") -> dict[str, str]:
    """Dicionário {id: nome} útil para selectboxes."""
    df = ler(tabela)
    if df.empty:
        return {}
    return dict(zip(df["id"], df[coluna]))


def utilizador_atual() -> str:
    """Email do utilizador autenticado no Streamlit Cloud, se disponível."""
    for acesso in ("user", "experimental_user"):
        origem = getattr(st, acesso, None)
        if origem is not None:
            email = getattr(origem, "email", None)
            if email:
                return email
    return "local"
