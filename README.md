# LeiteSol Monorepo

Base inicial de um monorepo com Python + React, separando responsabilidades para facilitar crescimento com SOLID, DDD e um gateway entre frontend e backend.

## Estrutura

```text
apps/
  api/       # Backend Python (FastAPI) organizado por camadas
  gateway/   # BFF/API gateway entre frontend e backend
  web/       # Frontend React + Vite
  agent/     # Agente comercial (biblioteca): catálogo, operações e fluxo da pergunta
packages/
  config/    # Configurações compartilhadas
  contracts/ # Tipos/contratos TypeScript compartilhados
```

## Decisões iniciais

- `apps/api` concentra regras de exposição HTTP e casos de uso do backend.
- `apps/gateway` atua como camada intermediária entre o React e a API Python.
- `apps/agent` concentra a lógica do agente; a API o importa e cuida de autenticação, alçada, conexões e rotas (ver `apps/agent/README.md`).
- `packages/contracts` centraliza contratos compartilhados do lado TypeScript.
- `turbo` e `pnpm workspace` organizam as aplicações JavaScript/TypeScript.
- `uv workspace` organiza os projetos Python de forma consistente.
- respostas HTTP seguem um envelope comum com `data`, `statusCode`, `message`, `error`, `success`, `traceId` e `timestamp`.

## Como começar

### JavaScript/TypeScript

```bash
npm install
npm run dev
```

Esse comando sobe:

- frontend Vite em `http://localhost:3000`
- gateway em `http://localhost:3001`

Para subir a API separadamente em desenvolvimento:

```bash
npm run dev:api
```

O agente (`apps/agent`) é uma dependência Python local da API. Para subir o
Uvicorn pelo workspace e instalar/resolver essa dependência corretamente:

```bash
uv run --package leitesol-api python -m uvicorn leitesol_api.main:app --reload --host 0.0.0.0 --port 5000
```

Evite executar `uvicorn leitesol_api.main:app` diretamente com um Python global:
nesse caso o interpretador pode encontrar `apps/api/src`, mas não
`apps/agent/src`, causando `ModuleNotFoundError: leitesol_agent`. O comando
`npm run dev:api` também prepara esses caminhos automaticamente quando usa o
ambiente virtual local da API.

Se quiser subir tudo junto:

```bash
npm run dev:full
```

Se preferir `pnpm`, ele tambem funciona para os workspaces JS:

```bash
pnpm install
pnpm dev
```

Para executar o agente separadamente:

```bash
pnpm dev:agent
```

## Health checks

- API FastAPI:
  - `GET /health` retorna o envelope padronizado
  - `GET /health/live` responde liveness via middleware
- Gateway:
  - `GET /api/health` consulta a API
  - `GET /health/live` responde liveness do gateway

## Logs do gateway e duração da sessão

Cada requisição recebida pelo gateway ganha um `X-Request-ID` novo. O gateway
propaga o identificador para a API e o devolve no cabeçalho da resposta. Um
registro JSON correlaciona método/rota da requisição com status/duração da
resposta. Senhas, cookies, tokens e query strings não são registrados. Para
diagnóstico do chat, o gateway e o backend também imprimem o evento JSON
`chat_exchange` com a pergunta e a resposta (`answer` e linhas de
`sqlResult`), correlacionados pelo mesmo `traceId`. Esses eventos são enviados
ao console/fluxo de logs dos serviços, não adicionados ao registro de auditoria no
Blob. Como podem conter dados comerciais, restrinja o acesso aos logs.
Respostas 4xx são warnings; respostas 5xx são errors.

Para persistir esses registros no Blob privado existente, configure o mesmo
valor aleatório em `LEITESOL_API_API_KEY` e `BACKEND_API_KEY` no `.env` da raiz
usado pelo Docker Compose (ou forneça as duas variáveis ao iniciar os serviços
diretamente), configure conta/container de Storage e defina
`LEITESOL_API_GATEWAY_LOG_TO_BLOB=true`. Todos os níveis e, quando
`LEITESOL_API_USAGE_LOG_TO_BLOB=true`, os registros de consumo da LLM são
anexados ao mesmo append blob `gateway/logs.jsonl`; cada linha JSONL identifica
severidade e tipo do evento, sem criar blobs por data ou categoria. O blob é
criado na primeira gravação se ainda não existir. Sem a gravação no Blob, os
logs estruturados continuam no console/fluxo de logs do gateway e da API. Falhas de
persistência são registradas como warning e não interrompem as requisições.

Tokens de acesso duram no máximo 20 minutos. A API valida expiração e idade
máxima do token nas rotas protegidas; o gateway mantém o access token em cookie
HttpOnly, valida a sessão ao carregar a página e volta à tela de login quando
o token expira ou uma chamada protegida retorna 401. A interface não renova a
sessão silenciosamente.

Para uma futura camada relacional de rastreabilidade, sugiro este conjunto
mínimo:

| Tabela | Finalidade / colunas principais |
| --- | --- |
| `RequestTrace` | Uma linha por chamada browser-gateway: `trace_id` (PK), `started_at`, `finished_at`, `method`, `path`, `status_code`, `duration_ms`, `severity`. |
| `ServiceCall` | Uma linha por chamada downstream: `call_id` (PK), `trace_id` (FK), `service`, `operation`, `started_at`, `finished_at`, `status_code`, `duration_ms`. |
| `TraceError` | Erros/warnings do trace ou chamada: `error_id` (PK), `trace_id` (FK), `call_id` (FK opcional), `occurred_at`, `severity`, `code`, `message` sanitizada. |
| `UserSession` | Ciclo de autenticação sem armazenar tokens: `session_id` (PK), `user_id` ou identificador pseudônimo, `created_at`, `expires_at`, `ended_at`, `end_reason`. |

Não armazene nessas tabelas corpos de request/response, bearer tokens, cookies ou
senhas. Use `trace_id` como chave comum do gateway até a API; `call_id` distingue
retries ou múltiplas chamadas downstream.

## Histórico de conversas

Implementado a partir do modelo sugerido abaixo, no schema **`IA_APP`** do
Warehouse `AgenteFaturamentoDW`, separado do `IA_COMERCIAL` do agente. O script
das tabelas e da permissão é o `17_historico_conversa.sql` do repositório de
documentação (`docs/projeto/modelo-semantico-fabric/sql/`).

- `IA_APP.CONVERSA` (Conversation) e `IA_APP.CONVERSA_MENSAGEM`
  (ConversationMessage). A `AgentExecution` virou colunas da mensagem do
  assistente (`OperacaoId`, `StatusResposta`, `CorrelationId`). A
  `MessageAttachment` não foi criada porque o MVP não recebe anexo.
- **Só inserção.** O Warehouse derruba `UPDATE`/`DELETE` concorrentes na mesma
  tabela. Por isso a data de atualização é a da última mensagem e não há
  exclusão lógica. A identidade do backend recebe só `SELECT` + `INSERT` em
  `IA_APP` e continua somente leitura em `IA_COMERCIAL`.
- Guarda o texto da pergunta e o da resposta, **não a tabela de resultado**.
  Ao reabrir uma conversa, a resposta volta só como texto.
- `POST /chat/query` aceita `chatId` (a tela manda o id da conversa ativa) e
  devolve `chatId`. Sem `chatId`, o backend gera um. A gravação roda depois da
  resposta, e uma falha ao gravar vira só um aviso no log.
- `GET /chats` lista as conversas do usuário logado (até 50, mais recentes
  primeiro) e `GET /chats/{chatId}` abre uma delas. Toda leitura filtra pelo
  dono: o e-mail do token do Entra ID, ou o nome do usuário no login local.
  Uma conversa de outro usuário responde 404. O gateway expõe as duas rotas em
  `/api/chats`.
- Fica desligado por padrão (`LEITESOL_API_CONVERSATION_HISTORY_ENABLED=false`).
  Só ligue depois de rodar o script e definir a política de retenção, porque a
  resposta pode conter valor comercial.

Falta na tela: listar as conversas (`listChats`) e reabrir uma delas
(`getChat`). Os dois já existem em `apps/web/src/shared/api.ts`.

Para persistir o conteúdo das conversas (separado dos logs técnicos), sugiro
este modelo relacional:

| Tabela | Finalidade / colunas principais |
| --- | --- |
| `Conversation` | Uma conversa pertencente ao usuário: `conversation_id` (PK), `user_id` (ou subject pseudonimizado), `title`, `status`, `created_at`, `updated_at`, `deleted_at`. |
| `ConversationMessage` | Mensagens ordenadas: `message_id` (PK), `conversation_id` (FK), `sequence_no`, `role` (`user`/`assistant`/`system`), `content`, `created_at`, `trace_id` (FK lógica para `RequestTrace`, nullable), `status`; unique (`conversation_id`, `sequence_no`). |
| `MessageAttachment` | Metadados e referência privada ao arquivo: `attachment_id` (PK), `message_id` (FK), `blob_key`, `file_name`, `mime_type`, `size_bytes`, `created_at`; armazenar o arquivo no Blob privado, não como binário SQL. |
| `AgentExecution` | Resultado técnico ligado à resposta: `execution_id` (PK), `message_id` (FK), `trace_id`, `operation_id`, `started_at`, `finished_at`, `status`, `error_code` sanitizado. |

Indexe `Conversation(user_id, updated_at)` e
`ConversationMessage(conversation_id, sequence_no)`. A API deve verificar a
propriedade da conversa em toda leitura/escrita, e a política de retenção deve
ser definida antes de persistir mensagens: elas podem conter dados comerciais
sensíveis. Não persista tokens, credenciais nem SQL com parâmetros sensíveis.

## Ditar perguntas por voz

O chat inclui o componente reutilizável `VoiceToText`, localizado em
`apps/web/src/shared/components/VoiceToText.tsx`. Ele não conhece o chat nem
controla o envio: recebe `onTranscript`, idioma, estado desabilitado e classe
opcional; o consumidor decide o que fazer com a transcrição. No chat, a fala é
acrescentada ao rascunho e precisa ser revisada e enviada pelo usuário.

O reconhecimento usa a Web Speech API do navegador; disponibilidade e suporte
variam por navegador. Requer HTTPS (ou localhost) e permissão do microfone. O
recurso não envia a pergunta automaticamente à API.

Exemplo de reutilização:

```tsx
<VoiceToText
  language="pt-BR"
  onTranscript={(text) => setValue((current) => `${current} ${text}`.trim())}
/>
```

## Criar especificações JSON de gráficos

`POST /chat/chart` (ou `/api/chat/chart` pelo gateway) transforma o resultado
tabular de uma consulta do agente em uma especificação JSON pronta para uma
biblioteca de gráficos no frontend. Use o `columns` e `rows` devolvidos por
`POST /chat/query` ou pelo fluxo de perguntas do agente e escolha a coluna de
categoria e uma ou mais colunas numéricas. A rota exige autenticação; não
executa SQL nem consulta o Fabric por conta própria — a fonte dos dados é a
consulta autenticada do agente, que já aplica a alçada do usuário e as regras
do catálogo/views.

Tipos disponíveis: `auto`, `bar`, `line` e `pie`. `auto` escolhe linha para
categorias de período/mês e barras para categorias como cliente ou UF. Pizza
aceita uma única série numérica. Filtros inválidos/valores não numéricos são
retornados como erro de validação; valores nulos são mantidos como lacunas.

Exemplo completo:

```bash
# 1. Obtenha uma sessão/token seguindo o fluxo de autenticação existente.
# 2. Pergunte ao agente e use sqlResult.columns e sqlResult.rows da resposta.
curl -X POST http://localhost:5000/chat/chart \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "columns": ["Competência", "FAT R$ atual", "FAT R$ ano anterior"],
    "rows": [
      {"Competência": "2026-01", "FAT R$ atual": 125000, "FAT R$ ano anterior": 108000},
      {"Competência": "2026-02", "FAT R$ atual": 131000, "FAT R$ ano anterior": 119000}
    ],
    "categoryColumn": "Competência",
    "valueColumns": ["FAT R$ atual", "FAT R$ ano anterior"],
    "chartType": "auto",
    "title": "Faturamento mensal: atual x ano anterior"
  }'
```

A resposta usa o envelope padrão da API (`data`, `statusCode`, `success`,
`traceId`) e contém `chartType`, `categories`, `series` e metadados dos eixos.
A mesma especificação pode ser passada a Recharts, Chart.js, ECharts ou outro
renderizador escolhido pela interface.

No chat, a operação OP17 gera automaticamente uma linha de tendência a partir
da série mensal, usando o endpoint autenticado `/chat/chart` (via gateway).
Comparações anuais OP12 também geram automaticamente um gráfico de barras:
totais são exibidos como período atual x mesmo período do ano anterior; quando
a consulta tem uma dimensão (por exemplo, UF ou produto), essa dimensão vira
categoria e os valores atual/anterior viram séries separadas. O chat escolhe
FAT R$ por padrão, ou FAT KG/TONS quando a pergunta pedir explicitamente essa
métrica, sem misturar unidades no mesmo gráfico. Consultas relativas OP12, como
“compare os 3 últimos meses com o mesmo período do ano passado”, usam as últimas
competências fechadas disponíveis e comparam com o intervalo equivalente do ano
anterior. Também aceitam qualquer quantidade positiva de meses. Períodos com
datas explícitas continuam sendo respeitados. Quando a pergunta lista os mesmos
meses em cada ano (por exemplo, “meses 5, 6 e 7 de 2026 contra os meses 5, 6 e 7
de 2025”), ou compara qualquer intervalo de 2 a 12 competências, o resultado
detalha cada mês, acrescenta o total do período e o gráfico de linhas mostra
uma série por ano com um ponto para cada competência. Competências sem
faturamento aparecem como zero no gráfico.
Informe uma janela por consulta: “evolução do faturamento dos últimos 3 meses”,
“6 meses”, “9 meses” ou “12 meses”. A janela padrão continua sendo 12 meses;
meses sem venda aparecem com zero e a tabela também contém a variação mensal.
As consultas e seus gráficos preservam a alçada comercial do usuário; ampliar
o período não amplia sua carteira.

Análises comerciais que podem alimentar esse fluxo, respeitando as operações
já implementadas no agente:

- **Ranking de vendedores:** “Quem vendeu mais FAT KG nos últimos três meses?”.
  O ranking usa a métrica solicitada, credita a venda ao vendedor atual do
  cliente e considera as competências fechadas; “FAT R$” pode ser pedido explicitamente.
  O ranking composto permanece indisponível até homologação comercial.
- **Ranking de produtos:** “Quais produtos tiveram maior volume vendido nos
  últimos 6 meses?”; por padrão, exibe Top 20 em FAT KG.
- **Vendas por região:** “Qual UF teve maior volume vendido?” usa a UF
  cadastral do cliente e lista os totais por UF. Se pedir explicitamente
  “região”, o agrupamento usa `Regiao` do cadastro, mapeada por
  `IA_COMUM.ESTADOS.REGIAO`. “Quais produtos venderam mais em cada UF?” lista
  o Top 5 por UF. A janela padrão dessas análises é de três competências
  fechadas, podendo ser 3, 6, 9 ou 12 meses.
- **Preço médio geral por kg:** “Qual foi a média de faturamento por quilo nos
  últimos 10 meses?” divide o FAT R$ total pelo FAT KG total das dez
  competências fechadas. Aceita qualquer quantidade positiva de meses e
  preserva a alçada e os filtros. É uma razão ponderada dos totais, não uma
  média simples dos preços mensais nem uma comparação por cliente (OP07).
- Essas consultas continuam sujeitas à alçada do usuário e aos filtros
  estruturados. O filtro geográfico usa o cadastro do cliente, não `UFVenda`.
  Elas são totais absolutos, não a comparação histórica regional descrita no
  catálogo OP16 ("quais regiões estão acima ou abaixo da média?"), que compara
  cada região com a própria média de 3, 6 e 12 meses e com o ano anterior.
- **Evolução mensal:** “Mostre a evolução do faturamento dos últimos 12 meses.” Use
  `Competência` no eixo X e FAT R$ ou FAT KG como série; `auto` escolhe linha.
- **Comparação anual:** “Compare o faturamento de janeiro a junho de 2026 com o
  mesmo período de 2025, por UF.” Use UF como categoria e as colunas de FAT R$
  atual/anterior como séries; barras ajudam a comparar os períodos.
- **Ranking de clientes:** “Quais foram os 20 clientes com maior volume de vendas
  no primeiro semestre de 2026?” Use Cliente como categoria e FAT KG como série;
  barras destacam a ordem do ranking.
- **Vendedores abaixo da média:** “Quais vendedores ficaram abaixo da própria
  média de faturamento dos três meses anteriores em agosto de 2026?” Use Vendedor
  como categoria e FAT R$ no mês/média como séries.

## Segurança inicial

- CORS configurável por variável de ambiente
- `TrustedHostMiddleware` no backend
- headers básicos de segurança no backend e gateway
- suporte a `X-API-Key` no backend para endurecer rotas não públicas quando necessário
- `X-Request-ID` propagado em logs e respostas

## Docker

Containers disponíveis:

- [apps/api/Dockerfile](C:/Users/Taking/Downloads/LeiteSol-AgenteComercial/apps/api/Dockerfile)
- [apps/gateway/Dockerfile](C:/Users/Taking/Downloads/LeiteSol-AgenteComercial/apps/gateway/Dockerfile)
- [apps/web/Dockerfile](C:/Users/Taking/Downloads/LeiteSol-AgenteComercial/apps/web/Dockerfile)

Subida de producao local:

```bash
docker compose up --build
```

Subida de desenvolvimento com containers:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Endpoints principais com Docker:

- frontend: `http://localhost:3000`
- gateway: `http://localhost:3001`
- backend: `http://localhost:5000`

## Azure

Os containers ja estao preparados para Azure com porta configuravel por variavel de ambiente:

- web: usa `PORT`, `API_PROXY_PASS` e `HEALTH_PROXY_PASS`
- gateway: usa `PORT`, `BACKEND_URL`, `BACKEND_API_KEY` e `CORS_ORIGINS`
- api: usa `PORT` e variaveis `LEITESOL_API_*`

Guia de publicacao:

- [docs/deployment/azure.md](C:/Users/Taking/Downloads/LeiteSol-AgenteComercial/docs/deployment/azure.md)

## Próximos passos recomendados

1. Adicionar autenticação no gateway.
2. Definir bounded contexts e agregados do domínio.
3. Evoluir o agente para uma interface própria ou integração assíncrona.
4. Criar pipelines de lint, testes e CI.
