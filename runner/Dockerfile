FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes docker-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY opspilot_runner ./opspilot_runner
RUN pip install --no-cache-dir . \
    && groupadd --gid 10001 opspilot \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app opspilot \
    && mkdir -p /var/lib/opspilot-runner \
    && chown -R 10001:10001 /app /var/lib/opspilot-runner

USER 10001:10001

CMD ["python", "-m", "opspilot_runner", "serve"]
