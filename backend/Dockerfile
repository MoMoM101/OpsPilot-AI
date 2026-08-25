# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app/__init__.py ./app/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip pip install .
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

RUN groupadd --gid 10001 opspilot \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app opspilot \
    && chown -R 10001:10001 /app

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
