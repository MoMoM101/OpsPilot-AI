FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY opspilot_lab ./opspilot_lab
RUN pip install --no-cache-dir . \
    && groupadd --gid 10002 lab \
    && useradd --uid 10002 --gid 10002 --no-create-home --home-dir /app lab \
    && mkdir -p /lab/data \
    && chown -R 10002:10002 /app /lab

USER 10002:10002

CMD ["uvicorn", "opspilot_lab.rag_api:app", "--host", "0.0.0.0", "--port", "8000"]
