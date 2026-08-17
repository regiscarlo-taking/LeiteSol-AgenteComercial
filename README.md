# LeiteSol Monorepo

Base inicial de um monorepo com Python + React, separando responsabilidades para facilitar crescimento com SOLID, DDD e um gateway entre frontend e backend.

## Estrutura

```text
apps/
  api/       # Backend Python (FastAPI) organizado por camadas
  gateway/   # BFF/API gateway entre frontend e backend
  web/       # Frontend React + Vite
  agent/     # Espaço dedicado para o agente comercial
packages/
  config/    # Configurações compartilhadas
  contracts/ # Tipos/contratos TypeScript compartilhados
```

## Decisões iniciais

- `apps/api` concentra regras de exposição HTTP e casos de uso do backend.
- `apps/gateway` atua como camada intermediária entre o React e a API Python.
- `apps/agent` fica isolado para evoluir o agente sem acoplar à API principal.
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

Ou, se preferir chamar diretamente o Uvicorn:

```bash
uvicorn leitesol_api.main:app --reload --host 0.0.0.0 --port 5000
```

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
