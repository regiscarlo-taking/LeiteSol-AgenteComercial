# API

Estrutura pensada para separar domínio, casos de uso, infraestrutura e interfaces.

- `domain/`: entidades e regras centrais
- `application/`: orquestração de casos de uso
- `infrastructure/`: config, providers e integrações
- `interfaces/`: entrada e saída, como rotas HTTP e schemas

## Executar localmente

Na raiz do repositório, use o launcher que configura o ambiente e o caminho de
importação dos dois pacotes Python:

```bash
npm run dev:api
```

Como alternativa, com `uv` instalado, execute a API como pacote do workspace:

```bash
uv run --package leitesol-api python -m uvicorn leitesol_api.main:app --reload --host 0.0.0.0 --port 5000
```

A API declara `leitesol-agent` como dependência de workspace. Executar Uvicorn
diretamente com um Python global ou com um ambiente que instalou apenas
`apps/api/requirements.txt` não instala automaticamente `apps/agent`; por isso
pode resultar em `ModuleNotFoundError: No module named 'leitesol_agent'`.
