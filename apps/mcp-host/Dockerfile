ARG HTTP_PROXY
ARG HTTPS_PROXY

FROM python:3.11-slim AS base

ARG HTTP_PROXY
ARG HTTPS_PROXY

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_NETWORK=rrfusion-net \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY}

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder

WORKDIR /build

COPY pyproject.toml README.md uv.lock ./
COPY src ./src
COPY apps ./apps
COPY infra ./infra

RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels ".[dev]"

FROM base

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY tests ./tests
COPY apps ./apps
COPY infra ./infra

RUN pip install --upgrade pip \
    && pip install --no-cache-dir /wheels/*.whl

CMD ["pytest"]
