# Build context is the repository root (see docker-compose.yml) so the
# skitak plugin package under server/ can be installed into the image.
FROM python:3.11-slim

# openssl: OTS shells out to it for CA/cert generation
# curl: container health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pin the OTS version so builds are reproducible — bump deliberately.
# psycopg (v3) matches OTS's postgresql+psycopg:// SQLAlchemy driver.
RUN pip install --no-cache-dir \
    opentakserver==1.7.11 \
    "psycopg[binary]"

# SkiTAK plugin — discovered by OTS via the opentakserver.plugin entry point
COPY server/ /opt/skitak-server/
RUN pip install --no-cache-dir /opt/skitak-server

COPY docker/opentakserver/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persistent data: config.yml, CA, uploads, logs — shared by all three processes
ENV OTS_DATA_FOLDER=/data/opentakserver
VOLUME ["/data/opentakserver"]

# 8081: Flask API + Socket.IO (internal, Nginx proxies this)
# 8089: CoT TLS streaming (eud_handler --ssl)
EXPOSE 8081 8089

ENTRYPOINT ["/entrypoint.sh"]
# Overridden per compose service: opentakserver | eud_handler --ssl | cot_parser
CMD ["opentakserver"]
