FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

WORKDIR /app

COPY apps/api /app/apps/api

FROM base AS dev

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/apps/api/requirements-dev.txt \
    && pip install --no-cache-dir -e /app/apps/api

WORKDIR /app/apps/api

EXPOSE 5000

CMD ["sh", "-c", "python -m uvicorn leitesol_api.main:app --host 0.0.0.0 --port ${PORT:-5000} --reload"]

FROM base AS prod

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /app/apps/api

WORKDIR /app/apps/api

EXPOSE 5000

CMD ["sh", "-c", "python -m uvicorn leitesol_api.main:app --host 0.0.0.0 --port ${PORT:-5000}"]
