# Gestão de Projetos

Aplicação Streamlit para gestão de projetos, tarefas e equipas, com cronograma
Gantt por disciplina. Dados partilhados numa folha do Google Sheets.

---

## Estrutura

```
gestao-projetos/
├── app.py                      Painel inicial (KPIs, atrasos, diagnóstico)
├── pages/
│   ├── 1_Cronograma.py         Gantt com filtros e exportação
│   ├── 2_Projetos.py           CRUD de projetos
│   ├── 3_Tarefas.py            CRUD de tarefas (com horas orçadas)
│   ├── 4_Equipas.py            Equipas, membros, perfis, custos
│   ├── 5_Registo_de_Horas.py   Temporizador, grelha semanal, lista, submissão
│   ├── 6_Aprovacoes.py         Aprovação de semanas e fecho de períodos
│   └── 7_Relatorios.py         Resumo, detalhado, semanal, orçamento, exportação
├── lib/
│   ├── config.py               Disciplinas, estados, esquema das folhas, regras de horas
│   ├── data.py                 ÚNICO ponto de acesso ao Google Sheets
│   ├── gantt.py                Construção do gráfico Plotly
│   ├── horas.py                Lógica do registo de horas (sem Streamlit, testável)
│   ├── sessao.py               Identificação do utilizador, perfis e permissões
│   └── exportar.py             Exportação para Excel (formato-padrão) e CSV
├── requirements.txt
├── .streamlit/
│   ├── config.toml             Tema
│   └── secrets.toml.example    Modelo de credenciais
└── .gitignore
```

O isolamento em `lib/data.py` é intencional: nenhuma página importa `gspread`
diretamente. Para migrar para Postgres ou SQLite basta reescrever esse ficheiro,
mantendo as assinaturas de `ler`, `inserir`, `atualizar` e `eliminar`.

---

## Parte 1 — Criar a folha de cálculo

1. Cria uma folha nova em <https://sheets.google.com>, com o nome que quiseres.
2. Copia o identificador do URL. Em
   `https://docs.google.com/spreadsheets/d/`**`1AbC...XyZ`**`/edit`,
   o identificador é a parte a negrito.

Não é preciso criar abas nem cabeçalhos: a aplicação cria-os no primeiro
arranque através do botão **Verificar esquema**, na barra lateral.

---

## Parte 2 — Conta de serviço Google

Uma conta de serviço é uma identidade não-humana que a aplicação usa para
aceder à folha. Não consome licenças nem precisa de autorizações de
administrador.

1. Vai a <https://console.cloud.google.com> e cria um projeto
   (ex.: `gestao-projetos`).
2. **APIs e serviços → Biblioteca** — ativa duas APIs:
   - *Google Sheets API*
   - *Google Drive API*
3. **APIs e serviços → Credenciais → Criar credenciais → Conta de serviço**.
   Dá-lhe um nome e conclui sem atribuir papéis (não são necessários).
4. Abre a conta de serviço criada → separador **Chaves** →
   **Adicionar chave → Criar nova chave → JSON**. O ficheiro é descarregado.
   **Guarda-o em local seguro e nunca o coloques no GitHub.**
5. Abre o JSON e copia o valor de `client_email`. Tem o aspeto
   `gestao-projetos@gestao-projetos-000000.iam.gserviceaccount.com`.
6. Volta à folha de cálculo, carrega em **Partilhar**, cola esse email e
   atribui permissão de **Editor**.

---

## Parte 3 — Configurar os secrets

Cria `.streamlit/secrets.toml` a partir do modelo `secrets.toml.example`,
preenchendo com os valores do JSON descarregado:

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n"
client_email = "gestao-projetos@....iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"

[sheets]
spreadsheet_id = "1AbC...XyZ"
```

**O campo `private_key` é o mais propenso a erro.** No JSON as quebras de linha
aparecem como `\n` literais. Mantém-nas exatamente assim, com a chave toda numa
única linha entre aspas. Se a colares com quebras de linha reais, a
autenticação falha com uma mensagem pouco esclarecedora sobre *padding*.

---

## Parte 4 — Correr localmente

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Abre <http://localhost:8501>. Se a barra lateral mostrar o indicador verde,
carrega em **Manutenção → Verificar esquema** para criar as abas.

---

## Parte 5 — Publicar no Streamlit Community Cloud

1. Cria um repositório no GitHub e envia o código.
   Confirma que `.streamlit/secrets.toml` **não** foi incluído — o `.gitignore`
   já o exclui, mas vale a pena verificar.
2. Em <https://share.streamlit.io>, **New app**, aponta para o repositório,
   ramo `main` e ficheiro `app.py`.
3. Antes do primeiro arranque, em **Advanced settings → Secrets**, cola o
   conteúdo integral do teu `secrets.toml`.
4. Depois de publicada: **Settings → Sharing** → desliga o acesso público e
   acrescenta os emails da equipa. Cada pessoa entra com a conta Google dela.

Após a publicação, a barra lateral mostra o email autenticado, e cada alteração
fica registada nas colunas `atualizado_por` e `atualizado_em`.

---

## Notas de funcionamento

**Cache.** As leituras são cacheadas 120 segundos (`CACHE_TTL` em
`lib/config.py`). Uma alteração feita por outra pessoa pode demorar até dois
minutos a aparecer; o botão **Atualizar dados** força a releitura imediata.

**Escrita simultânea.** O Google Sheets não tem bloqueio de linha. Se duas
pessoas editarem o mesmo registo ao mesmo tempo, prevalece a última gravação.
Para uma equipa pequena é aceitável; acima de uma dúzia de utilizadores
simultâneos convém migrar para Postgres.

**Limites da API.** 60 leituras e 60 escritas por minuto por conta de serviço
(é partilhada por toda a equipa). A cache e as escritas em lote (a grelha
semanal grava tudo em no máximo três chamadas) mantêm o consumo bem abaixo
disso para 7 pessoas.

**Datas e números.** A aplicação escreve na folha em modo *RAW* (texto exato),
para não depender da localização da folha: numa folha em português, «1.5»
podia ser lido como 1 de maio. Datas em ISO (`AAAA-MM-DD`), horas em `HH:MM`,
durações em minutos inteiros. Na leitura aceita-se também `DD/MM/AAAA` e vírgula
decimal, caso alguém edite diretamente no Sheets.

---

## Registo de horas

### Ativação (instalação existente)

1. Substitui os ficheiros do repositório por esta versão e faz *commit*. O
   Streamlit Cloud reinstala as dependências automaticamente.
2. Acrescenta aos *secrets* a secção `[app]` com o teu email em `admins`
   (ver `secrets.toml.example`).
3. Na barra lateral: **Manutenção → Verificar esquema**. Cria as abas
   `clientes`, `taxas`, `registos`, `submissoes` e `periodos_fechados`, e
   acrescenta as colunas novas a `projetos`, `tarefas` e `membros`. Os dados
   existentes não são alterados.
4. Em **Equipas → Membros**, confirma que cada pessoa tem o **email exato** com
   que entra na aplicação e atribui perfil, horas semanais e custo interno.
5. Em **Projetos → Clientes**, cria os clientes e associa-os aos projetos. O
   campo de cliente em texto dos projetos antigos continua a ser mostrado até
   escolheres um cliente da lista.

### Perfis

| Perfil | Pode |
|---|---|
| colaborador | Registar e submeter as próprias horas; ver os próprios relatórios |
| gestor | O anterior, mais: ver e corrigir as horas da sua equipa, aprovar/devolver/reabrir semanas, ver custos, valores e orçamentos |
| admin | Tudo, incluindo perfis, emails, custos e taxas dos membros, taxas por projeto × membro e fecho de períodos |

Um gestor não aprova as próprias semanas (ficam para um admin). Um admin pode
aprovar as suas, porque numa equipa pequena pode ser o único.

### Formas de registar

- **Temporizador.** Um por pessoa. A hora de arranque fica gravada na folha,
  por isso sobrevive a fechar o browser ou mudar de computador.
- **Grelha semanal.** Horas decimais por atividade e dia. Ao reduzir uma
  célula, a aplicação só mexe nos registos criados pela própria grelha; se a
  célula tiver registos do temporizador ou manuais, pede para os editar na Lista.
- **Lista.** Registo a registo, com início/fim, descrição, tags e faturável.

Tudo é arredondado a 15 minutos (`ARREDONDAMENTO_MIN` em `lib/config.py`).
Registos com mais de 10 h ficam assinalados com ⚠️ e destacados na aprovação.

### Ciclo de aprovação

Aberta → **Submetida** → Aprovada (bloqueada) ou Devolvida (com comentário,
volta a ser editável). O gestor pode reabrir uma semana aprovada, com motivo.
O admin pode **fechar um período** até uma data: tudo o que estiver para trás
fica bloqueado para todos, independentemente do estado das semanas.

### Taxas e custos

Taxa de faturação, por ordem de precedência: específica projeto × membro
(**Projetos → Taxas por membro**) → taxa do projeto → taxa do membro → 0.
O custo interno é sempre o do membro. Os valores são calculados no momento do
relatório com as taxas em vigor, pelo que alterar uma taxa altera também os
relatórios de períodos anteriores. Para congelar valores de um período já
faturado, exporta o relatório antes de mudar a taxa.

### Orçamentos

Horas orçadas por projeto e por tarefa. Aviso aos 80 % e alerta aos 100 %
(`ALERTA_ORCAMENTO`), no painel inicial para gestores, ao escolher a atividade
no temporizador e no separador **Orçamento** dos relatórios.

### Fuso horário

O servidor do Streamlit Cloud corre em UTC. As horas do temporizador, as datas
de «hoje» e os carimbos `atualizado_em` são convertidos para `Europe/Lisbon`
(`FUSO` em `lib/config.py`).

### Correr em local

Sem autenticação, o email é «local». Acrescenta `modo_local = true` à secção
`[app]` do `secrets.toml` local para escolher na barra lateral o membro a
simular. **Nunca** o ponhas nos secrets da app publicada.

### Limitações conhecidas

- Os feriados não são considerados no cálculo de dias abaixo da meta.
- Sem modo offline, extensão de browser nem notificações.
- Escrita simultânea no mesmo registo: prevalece a última gravação.

---

## Disciplinas configuradas

| Código | Descrição |
|--------|-----------|
| ME5 | Gases medicinais |
| ME7 | Ar comprimido industrial |
| ME8 | Esterilização |
| ME9 | Refrigeração |
| AVAC | Climatização e ventilação |
| ELE | Instalações elétricas |
| HID | Hidráulica e drenagem |
| GER | Geral / transversal |

Para acrescentar ou alterar disciplinas, edita o dicionário `DISCIPLINAS` em
`lib/config.py`. As cores do Gantt são lidas daí.
