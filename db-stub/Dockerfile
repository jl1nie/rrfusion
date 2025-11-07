FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY db-stub /app/db-stub

RUN pip install --no-cache-dir ".[dev]" && pip install --no-cache-dir uvicorn

EXPOSE 8080

CMD ["uvicorn", "db-stub.app:app", "--host", "0.0.0.0", "--port", "8080"]
