FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_NETWORK=rrfusion-net

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps

WORKDIR /deps

COPY pyproject.toml README.md uv.lock ./
COPY src ./src
COPY apps ./apps
COPY infra ./infra
COPY AGENT.md ./AGENT.md

RUN pip install --upgrade pip \
    && pip install --no-cache-dir ".[dev]"

FROM base

WORKDIR /app

COPY --from=deps /usr/local /usr/local
COPY pyproject.toml README.md uv.lock ./
COPY src ./src
COPY tests ./tests
COPY apps ./apps
COPY infra ./infra
COPY AGENT.md ./AGENT.md

CMD ["pytest"]
