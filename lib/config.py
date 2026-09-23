"""Constantes e configuração central da aplicação.

Todos os valores de domínio (disciplinas, estados, cores) vivem aqui para que
as páginas não tenham literais espalhados.
"""

APP_NOME = "Gestão de Projetos"
APP_ICON = "📐"

# --------------------------------------------------------------------------
# Disciplinas
# --------------------------------------------------------------------------
DISCIPLINAS = {
    "ME5": {"desc": "Gases medicinais", "cor": "#1F6FB2"},
    "ME7": {"desc": "Ar comprimido industrial", "cor": "#2E9E8F"},
    "ME8": {"desc": "Esterilização", "cor": "#7B5EA7"},
    "ME9": {"desc": "Refrigeração", "cor": "#4AA3DF"},
    "AVAC": {"desc": "Climatização e ventilação", "cor": "#D97706"},
    "ELE": {"desc": "Instalações elétricas", "cor": "#C2410C"},
    "HID": {"desc": "Hidráulica e drenagem", "cor": "#0E7490"},
    "GER": {"desc": "Geral / transversal", "cor": "#6B7280"},
}

DISCIPLINAS_KEYS = list(DISCIPLINAS.keys())
CORES_DISCIPLINA = {k: v["cor"] for k, v in DISCIPLINAS.items()}


def rotulo_disciplina(codigo: str) -> str:
    info = DISCIPLINAS.get(codigo)
    return f"{codigo} — {info['desc']}" if info else codigo


# --------------------------------------------------------------------------
# Estados
# --------------------------------------------------------------------------
ESTADOS_TAREFA = ["Por iniciar", "Em curso", "Em revisão", "Concluída", "Suspensa"]
ESTADOS_PROJETO = ["Ativo", "Em pausa", "Concluído", "Arquivado"]

FASES = [
    "Estudo prévio",
    "Projeto base",
    "Projeto de execução",
    "Assistência técnica",
    "Obra",
    "Transversal",
]

# --------------------------------------------------------------------------
# Esquema das folhas de cálculo
# A ordem das colunas define a ordem no Google Sheets. Alterar aqui implica
# correr novamente o arranque da aplicação para acrescentar colunas em falta.
# --------------------------------------------------------------------------
SCHEMAS = {
    "projetos": [
        "id",
        "codigo",
        "nome",
        "cliente",
        "cliente_id",
        "estado",
        "data_inicio",
        "data_fim",
        "responsavel_id",
        "notas",
        "horas_orcadas",
        "taxa_hora",
        "faturavel",
        "atualizado_por",
        "atualizado_em",
    ],
    "tarefas": [
        "id",
        "projeto_id",
        "nome",
        "disciplina",
        "fase",
        "responsavel_id",
        "data_inicio",
        "data_fim",
        "progresso",
        "estado",
        "depende_de",
        "notas",
        "horas_orcadas",
        "atualizado_por",
        "atualizado_em",
    ],
    "equipas": [
        "id",
        "nome",
        "descricao",
        "atualizado_por",
        "atualizado_em",
    ],
    "membros": [
        "id",
        "equipa_id",
        "nome",
        "email",
        "funcao",
        "ativo",
        "perfil",
        "custo_hora",
        "taxa_hora",
        "horas_semana",
        "atualizado_por",
        "atualizado_em",
    ],
    # ---- Registo de horas ------------------------------------------------
    "clientes": [
        "id",
        "nome",
        "nif",
        "contacto",
        "notas",
        "atualizado_por",
        "atualizado_em",
    ],
    # Taxa específica de um membro num projeto (sobrepõe-se à do projeto)
    "taxas": [
        "id",
        "projeto_id",
        "membro_id",
        "taxa_hora",
        "atualizado_por",
        "atualizado_em",
    ],
    "registos": [
        "id",
        "membro_id",
        "projeto_id",
        "tarefa_id",
        "data",
        "hora_inicio",      # HH:MM, vazio em registos da grelha semanal
        "hora_fim",         # HH:MM
        "duracao_min",      # inteiro, múltiplo de ARREDONDAMENTO_MIN
        "descricao",
        "tags",             # separadas por vírgula
        "faturavel",        # Sim / Não
        "estado",           # Em curso (temporizador ativo) / Concluído
        "inicio_ts",        # AAAA-MM-DD HH:MM:SS, hora de arranque do temporizador
        "origem",           # temporizador / manual / grelha
        "atualizado_por",
        "atualizado_em",
    ],
    "submissoes": [
        "id",
        "membro_id",
        "semana",           # segunda-feira da semana, AAAA-MM-DD
        "estado",           # Submetida / Aprovada / Devolvida
        "submetido_em",
        "revisto_por",
        "revisto_em",
        "comentario",
        "atualizado_por",
        "atualizado_em",
    ],
    "periodos_fechados": [
        "id",
        "data_fecho",       # tudo até esta data (inclusive) fica bloqueado
        "motivo",
        "atualizado_por",
        "atualizado_em",
    ],
}

# Colunas tratadas como datas (formato ISO YYYY-MM-DD na folha)
COLUNAS_DATA = {"data_inicio", "data_fim", "data", "semana", "data_fecho"}

# Colunas numéricas: percentagem (limitada a 0–100) e valores livres (>= 0)
COLUNAS_NUM = {"progresso"}
COLUNAS_NUM_LIVRE = {"duracao_min", "horas_orcadas", "taxa_hora", "custo_hora", "horas_semana"}

# Tempo de vida da cache de leitura, em segundos.
# Subir reduz chamadas à API; descer torna as alterações de colegas mais
# imediatas. 120 s é um compromisso razoável para uma equipa pequena.
CACHE_TTL = 120


# --------------------------------------------------------------------------
# Registo de horas
# --------------------------------------------------------------------------
# Fuso horário de referência. O servidor do Streamlit Cloud corre em UTC;
# todas as horas da aplicação são convertidas para este fuso.
FUSO = "Europe/Lisbon"

PERFIS = ["colaborador", "gestor", "admin"]
PERFIL_DESC = {
    "colaborador": "Regista e submete as próprias horas",
    "gestor": "Aprova as horas da sua equipa; vê custos e orçamentos",
    "admin": "Acesso total, incluindo taxas, perfis e fecho de períodos",
}

ARREDONDAMENTO_MIN = 15          # granularidade dos registos
LIMITE_HORAS_REGISTO = 10        # registos acima disto ficam sinalizados
HORAS_SEMANA_OMISSAO = 40
ALERTA_ORCAMENTO = (0.80, 1.00)  # aviso e excedido

ESTADOS_SUBMISSAO = ["Submetida", "Aprovada", "Devolvida"]

TAGS_SUGERIDAS = [
    "Reunião",
    "Coordenação",
    "Esclarecimentos concurso",
    "Revisão",
    "Visita de obra",
    "Modelação BIM",
    "Cálculo",
    "Peças escritas",
    "Peças desenhadas",
    "Administrativo",
    "Formação",
]

DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
