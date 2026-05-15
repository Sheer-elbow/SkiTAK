FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openssl \
    libssl-dev \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install OpenTAKServer and PostgreSQL driver
# Pin the version so builds are reproducible — bump deliberately
RUN pip install --no-cache-dir \
    opentakserver==1.7.11 \
    psycopg2-binary \
    gunicorn

# SkiTAK extensions package (mounted in at runtime in dev, copied in prod)
COPY skitak_extensions/ /app/skitak/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persistent data: certs, uploads, config
VOLUME ["/data/opentakserver"]

# CoT TLS streaming
EXPOSE 8089
# Flask API (internal, Nginx proxies this)
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
