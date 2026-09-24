# Análise do código — branch `analise/revisao-24-09`

**Base:** `master@bcbba86` (24-09-2026) · **Referências:** `06-contrato-dados-backend.md`, `sql/14_permissao_agente.sql`, `arquitetura-final-agente.md`, decisões D-J03, D-A15, D-A30, D-A45.

> **Contexto.** Sem container no Azure do cliente e sem usuário de serviço (P-INFRA, P-CONEXAO), o código foi feito para **responder alguma coisa ponta a ponta** com o que existe. Os itens abaixo são o que falta para chegar ao desenho do contrato, não erros de quem escreveu. O bloco 1 (contenção) foi aplicado nesta branch; ver o fim do documento.

Ordem: (1) segurança e aderência à arquitetura, (2) contrato de dados, (3) qualidade geral. Cada item traz arquivo, o problema e a correção proposta. Severidade: 🔴 bloqueia entrega · 🟠 corrigir antes de homologar · 🟡 melhoria.

---

## 1. Segurança e aderência à arquitetura

### 1.1 🔴 O `/chat/query` é um navegador de tabelas, não o agente do catálogo
`routes/chat.py` + `infrastructure/gemini.py`: o Gemini escolhe **uma entidade** da allowlist, depois `limit` e `ORDER BY`, e a API devolve `SELECT TOP n *` dessa entidade. Não é SQL livre: a allowlist e a validação da coluna de ordenação impedem injeção. Isso é correto e deve ficar. Mas:

- **Não usa as operações.** A D-J03 diz que a LLM *seleciona uma operação* de `AGT_OPERACAO` (22 operações, 212 parâmetros). O código não lê `AGT_OPERACAO`, `AGT_OPERACAO_PARAMETRO` nem `AGT_INTENCAO_EXEMPLO`.
- **Não agrega.** Linha crua de `vw_fato_faturamento` não responde a nenhuma das 22 perguntas. "Faturamento de agosto" vira "as 100 primeiras linhas da fato".
- **A resposta é escrita antes do dado.** O `answer` é a explicação do *plano* gerada pelo Gemini antes da consulta. Não é o insight sobre o resultado.

**Correção:** manter o `FabricSqlConnection` como camada de acesso e trocar o fluxo pelo do contrato §2: classificador → `operacao_id`, validador de parâmetros, executor com a query da operação, compositor. É a frente A2.6/A2.7 do plano, e o código atual serve de esqueleto.

### 1.2 🔴 Sem identidade do usuário, portanto sem alçada (RLS)
`infrastructure/auth.py`: o login é **um único usuário** (`basic_auth_username`, padrão `admin`) com senha bcrypt no `.env`, e a API emite o próprio JWT (HS256). Não há Entra ID do usuário final. O `sub` do token nunca chega à consulta.

- Todo mundo que loga vê **toda a base**. O contrato §5.2 diz: sem e-mail individual, só se libera o agente ao grupo que vê tudo, e a resposta **nunca** sai sem recorte.
- `entra_id.py` existe, mas é *client credentials* da aplicação, não login do usuário.

**Correção:** validar token do Entra ID (OIDC, `aud` = app da API) em `verify_token`, extrair o e-mail, resolver a alçada (`RLS_USUARIO_EQUIPE` + `vw_hierarquia_equipe`) e responder `sem_alcada` quando não houver linha. Enquanto P-INTRANET não fecha, restringir por grupo do Entra ("vê tudo"). O login local pode ficar **só** em `environment=development`.

### 1.3 🔴 A allowlist expõe o que o desenho proíbe
`infrastructure/fabric.py`, `CATALOG_ENTITIES`:

| Entidade | Problema |
|---|---|
| 7 × `AGT_GESTAO_*` | D-A15: ficam **fora** do agente. `14_permissao_agente.sql` dá `DENY`. Se a consulta **funcionar**, é evidência de P-APPPERM: a identidade tem mais do que devia |
| `vw_rls_alcance`, `vw_hierarquia_equipe` | São de **segurança**: e-mail × equipe. Não podem ser listadas para o usuário nem para a LLM |
| `vw_fato_faturamento`, `vw_dim_cliente` com `SELECT *` | Linha a linha com cliente e CNPJ para o front e para o Gemini, contra o princípio de **dado mínimo** (P1/R8, LGPD) |

**Correção:** tirar `AGT_GESTAO_*` e as views de segurança da lista. Separar as entidades de **catálogo** (lidas pelo backend) das de **dados** (lidas só pelo executor da operação, nunca expostas por rota).

### 1.4 🟠 Rotas `/fabric/*` expõem a base para qualquer token
`routes/measures.py`: `/fabric/entities` e `/fabric/query` devolvem qualquer entidade da allowlist, inclusive as do item 1.3, para qualquer usuário autenticado. O `sql` gerado também volta na resposta.

**Correção:** remover `/fabric/query` e `/fabric/entities` ou deixá-las só em `development`. Não devolver `sql` fora de `development`. `/fabric/measures` pode virar `GET /catalogo/*` (contrato §6).

### 1.5 🟠 Uma só identidade para tudo, com segredo fora do Key Vault
`azure_storage.py` + `fabric.py`: o mesmo service principal (`ENTRA_CLIENT_ID/SECRET`) lê o Warehouse, o Key Vault e o Blob. O contrato §1 diz que histórico e log vão para o Blob **com outra identidade**. O *secret* desse SP vem do `.env`, e só a chave do Gemini vem do Key Vault. No `get_gemini_client`, a variável de ambiente tem precedência sobre o Key Vault. (O Key Vault estava vazio em 24-09.)

**Correção:** no container, Managed Identity ou *workload identity*, sem secret no `.env`. Identidade de dados só com `SELECT`, identidade da aplicação para Blob. Em `production`, o segredo vem do Key Vault e a variável de ambiente é ignorada.

### 1.6 🟡 Diversos
- `main.py`: `/docs`, `/redoc` e `/openapi.json` ficam abertos em produção. Desligar em `production`.
- `main.py`: `ApiKeyMiddleware` não faz nada (é um *pass-through*) e o gateway manda `x-api-key` à toa. Remover ou implementar.
- `routes/auth.py`: o `/token/refresh` recebe o refresh token como **query string**, que vai parar em log de proxy. Passar no corpo.
- `auth.py`: com `jwt_secret_key` vazio fora de produção, o PyJWT levanta `InvalidKeyError`, que não é capturado e vira 500. Falha fechada, mas com erro feio. Exigir o segredo em todo ambiente que não seja `development`.
- `web/AuthGate.tsx`: access e refresh token em `localStorage`. Com Entra ID (MSAL), isso muda de qualquer forma.
- `main.py`: o handler genérico devolve `str(exc)` fora de produção. Aceitável em dev; conferir que *staging* não fica exposto.

---

## 2. Contrato de dados (`06-contrato-dados-backend.md`)

| Contrato | Código hoje | Ação |
|---|---|---|
| §1 Números **sempre pelas medidas** do modelo semântico (DAX via `executeQueries`/XMLA) | Não há conector do modelo semântico. Só T-SQL no Warehouse | Criar o conector DAX (token `analysis.windows.net`), ou decidir formalmente que as operações rodam em T-SQL sobre as `mv_*`/`vw_*` (é a A2.16) |
| §2 Fluxo em 7 etapas | 2 chamadas ao Gemini + `SELECT *` | Ver 1.1 |
| §3 Views | Faltam `vw_dim_cep` (D-A40) e `vw_produto_termo` (D-A34). Ignora as `mv_*` materializadas | Atualizar a lista. O executor lê as `mv_*` quando existirem |
| §5.1 Filtros de universo | Nenhum. `FlagProdutoAcabado = 1` (RT13) e `FlagExterior = 0` (RT14) não são aplicados | Aplicar no executor, em toda query de faturamento |
| §5.3 Período | Não há. Mês fechado e período parcial não existem | Implementar com `vw_dim_calendario.MesFechado` + `AGT_PARAM_FECHAMENTO` |
| §5.4 Entrada | Pergunta livre (até 4.000 caracteres) direto no prompt | Validar parâmetros contra `dominio_valores`. Termos de produto contra `vw_produto_termo` |
| §5.5 Saída | Linhas cruas | Arredondamento de KG (RT16), exceções separadas, sem causa inferida (RT09) |
| §6 Envelope (`status`, `operacao`, `periodo`, `recorte`, `avisos`…) | `answer` + `sqlResult` | Adotar o envelope. `status` ∈ respondida / esclarecimento / fora_de_escopo / sem_alcada / erro |
| `AGT_MEDIDA` (colunas) | Bate com o DDL (`medida_id`…`visivel_agente`) | ok, mas filtrar `visivel_agente` |

---

## 3. Qualidade geral

- 🔴 **O container de produção não conecta no Warehouse.** O `apps/api/Dockerfile` usa `python:3.12-slim` e instala `pyodbc`, mas **não instala o `msodbcsql18`** (ODBC Driver 18 for SQL Server), que é o driver configurado. Em produção, `pyodbc.connect` falha com "driver not found". Funciona na máquina do Regis porque o driver está no sistema dele. Isso pesa para a D-A44: o erro apareceria no ambiente do cliente e seria **nosso**. Correção: instalar `msodbcsql18` e `unixodbc` no Dockerfile (repositório da Microsoft).
- 🟠 **Uma conexão ODBC nova por chamada.** O `/chat/query` abre duas (`describe_entity` e `query_entity`), sem pool, e lê o Key Vault a cada pergunta. Criar o repositório uma vez (dependência do FastAPI), com pool e cache do segredo.
- 🟠 **Código síncrono em `def`** com rede bloqueante (pyodbc, httpx síncrono). O FastAPI roda isso em *threadpool*, então funciona, mas com o Gemini levando até 30 s o pool esgota com pouca carga. Considerar `async` no Gemini.
- 🟠 **Container roda como root.** Adicionar `USER`.
- 🟠 **Testes:** 3 testes de health, todos passando (verificado em 24-09). Não há teste de `fabric.py`, `gemini.py`, `auth.py` nem das rotas. No mínimo: allowlist (entidade fora recusada, `AGT_GESTAO_*` recusada), validação do plano do Gemini, token inválido ou expirado.
- 🔴 **`apps/web/src`** tem os `.js` compilados commitados ao lado dos `.tsx`. Não é só sujeira: o `build` roda `tsc -p` **sem `noEmit`**, então cada build gera `.js` ao lado do fonte, e o Vite resolve `.js` **antes** de `.tsx`. Resultado: a interface servida é a versão compilada antiga (o `ChatWorkspace.js` commitado nem mostra o resultado do chat). Corrigido no bloco 1.
- 🟡 **`apps/agent`** é um esqueleto (só `agent_profile`). Decidir se o núcleo do agente fica em `apps/agent` ou dentro da `api`. Hoje a lógica está na `api`.
- 🟡 **Gateway:** a lista, criação e mensagens de chat usam `mock-chat-service` (memória). O histórico real vai para o Blob (contrato §1).
- 🟡 **Dependências** com faixa (`>=,<`), não pinadas. Gerar lock (`pip-compile`/`uv`) para build reproduzível.
- 🟡 **Repositório público** com a URL do Key Vault do cliente no `.env.example`. Tornar privado e mover para o GitLab da Leitesol (D-A41).

---

## Proposta de ordem de correção (nesta branch)

1. **Contenção (pequeno, sem mudar arquitetura):** allowlist sem `AGT_GESTAO_*` e sem views de segurança. `/fabric/query` e `/fabric/entities` e o `sql` na resposta só em dev. Docs desligados em produção. Refresh token no corpo. ODBC Driver 18 e `USER` no Dockerfile. Testes da allowlist.
2. **Identidade:** Entra ID no `verify_token`, resolução de alçada e `sem_alcada`.
3. **Núcleo do agente:** loader do catálogo, classificador → `operacao_id`, validador, executor com filtros §5.1/§5.3, envelope §6. Começar por 1 ou 2 operações ponta a ponta (ex.: OP12 comparar ano anterior).

---

## Bloco 1 — aplicado nesta branch (24-09)

| Item | Mudança | Verificação |
|---|---|---|
| 1.3 | `AGT_GESTAO_*`, `vw_hierarquia_equipe` e `vw_rls_alcance` fora de `CATALOG_ENTITIES` (22 entidades restam) | `tests/test_security.py` |
| 1.4 | `/fabric/entities` e `/fabric/query` respondem 404 fora de `development`; `sql` só volta em `development` (`sql` virou opcional na API, no gateway, nos contratos e no web) | teste + checagem manual em dev (200) |
| 1.6 | `/docs`, `/redoc` e `/openapi.json` desligados em `production` | teste |
| 1.6 | `/token/refresh` recebe o token no corpo (`{"refresh_token": …}`); query string dá 422. Nenhum cliente chamava a rota | teste |
| 3 | `Dockerfile`: `msodbcsql18` + `unixodbc` pelo repositório da Microsoft e `USER app` no estágio `prod` | ⚠️ **build não verificado** (sem Docker nesta máquina) |
| 3 | Web: `noEmit: true` no `tsconfig`, `.js` compilados removidos e ignorados no `.gitignore` | ⚠️ **`tsc` não rodado** (sem Node nesta máquina) |

Suíte da API: **19 testes, todos passando** (eram 3).
