FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

WORKDIR /app

# pyodbc precisa do ODBC Driver 18 for SQL Server (LEITESOL_API_FABRIC_DRIVER)
# para conectar no Warehouse do Fabric; a imagem slim não traz o driver.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && . /etc/os-release \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/${VERSION_ID}/prod ${VERSION_CODENAME} main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

FROM runtime AS base

# A API importa o agente (apps/agent) como biblioteca.
COPY apps/agent /app/apps/agent
COPY apps/api /app/apps/api

FROM base AS dev

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/apps/api/requirements-dev.txt \
    && pip install --no-cache-dir -e /app/apps/agent -e /app/apps/api

WORKDIR /app/apps/api

EXPOSE 5000

CMD ["sh", "-c", "python -m uvicorn leitesol_api.main:app --host 0.0.0.0 --port ${PORT:-5000} --reload"]

# Instala agente + API num venv separado; a imagem final leva so o venv,
# sem o codigo-fonte, o pip de build e os arquivos do projeto.
FROM python:3.12-slim AS build

COPY apps/agent /src/apps/agent
COPY apps/api /src/apps/api

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir /src/apps/agent /src/apps/api

FROM runtime AS prod

ENV PATH=/opt/venv/bin:$PATH

COPY --from=build /opt/venv /opt/venv

RUN useradd --system --uid 10001 --no-create-home app

WORKDIR /app

USER app

EXPOSE 5000

CMD ["sh", "-c", "python -m uvicorn leitesol_api.main:app --host 0.0.0.0 --port ${PORT:-5000}"]
