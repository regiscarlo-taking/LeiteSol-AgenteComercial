# Azure Deployment

Esta base ja esta preparada para publicar os containers separadamente no Azure App Service ou no Azure Container Apps.

## Containers

- `apps/web/Dockerfile`
  - target `prod`
  - porta padrao `3000`
  - variaveis esperadas:
    - `PORT`
    - `API_PROXY_PASS`
    - `HEALTH_PROXY_PASS`

- `apps/gateway/Dockerfile`
  - target `prod`
  - porta padrao `3001`
  - variaveis esperadas:
    - `PORT`
    - `BACKEND_URL`
    - `BACKEND_API_KEY`
    - `CORS_ORIGINS`

- `apps/api/Dockerfile`
  - target `prod`
  - porta padrao `5000`
  - variaveis esperadas:
    - `PORT`
    - `LEITESOL_API_ENVIRONMENT`
    - `LEITESOL_API_ALLOWED_ORIGINS`
    - `LEITESOL_API_ALLOWED_HOSTS`
    - `LEITESOL_API_API_KEY`

## Fluxo recomendado

1. Publicar a API primeiro.
2. Publicar o gateway apontando `BACKEND_URL` para a URL publica da API.
3. Publicar o frontend apontando:
   - `API_PROXY_PASS` para `https://<gateway-url>/api/`
   - `HEALTH_PROXY_PASS` para `https://<gateway-url>/health/`

## Exemplo de build local

```bash
docker build -f apps/api/Dockerfile --target prod -t leitesol-api .
docker build -f apps/gateway/Dockerfile --target prod -t leitesol-gateway .
docker build -f apps/web/Dockerfile --target prod -t leitesol-web .
```

## Portas

- frontend: `3000`
- gateway: `3001`
- api: `5000`
