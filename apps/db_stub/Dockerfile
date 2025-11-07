FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md uv.lock /app/
COPY src /app/src
COPY apps/db_stub /app/db_stub

RUN pip install --no-cache-dir ".[dev]" && pip install --no-cache-dir uvicorn

EXPOSE 8080

CMD ["uvicorn", "db_stub.app:app", "--host", "0.0.0.0", "--port", "8080"]
