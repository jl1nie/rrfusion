ARG HTTP_PROXY
ARG HTTPS_PROXY

FROM python:3.11-slim AS builder

ARG HTTP_PROXY
ARG HTTPS_PROXY

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY}

COPY pyproject.toml README.md uv.lock /app/
COPY src /app/src
COPY apps/db_stub /app/db_stub

RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix /install ".[dev]" uvicorn

FROM python:3.11-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY}

COPY --from=builder /install /usr/local
COPY src /app/src
COPY apps/db_stub /app/db_stub

EXPOSE 8080

CMD ["uvicorn", "db_stub.app:app", "--host", "0.0.0.0", "--port", "8080"]
