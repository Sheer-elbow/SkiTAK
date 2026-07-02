# SkiTAK Deployment Guide

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A domain name pointing to your server (for production)
- Ports open: `443`, `8089` (plus `64738` TCP+UDP if the voice profile is enabled)

## Architecture at a glance

The stack runs OpenTAKServer 1.7.x as three processes from one image, the way
upstream's installer does with systemd:

| Service | Role | Exposure |
|---|---|---|
| `opentakserver` | Flask API, Socket.IO, plugin host (SkiTAK endpoints) | internal `:8081`, proxied by Nginx |
| `eud-handler` | CoT TLS streaming listener for TAK clients | public `:8089` |
| `cot-parser` | CoT parsing/routing worker | internal only |
| `postgres` (PostGIS), `rabbitmq`, `nginx`, `mbtileserver` | supporting services | only `nginx` is public |

The SkiTAK extensions are a pip-installed OTS plugin (`server/`), discovered via
the `opentakserver.plugin` entry point. It applies its own database schema at
startup, so schema changes ship with the image.

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/Sheer-elbow/SkiTAK
cd SkiTAK

# 2. Run setup (creates docker/.env from template)
make setup

# 3. Edit your environment — all of these are required:
#    SERVER_HOSTNAME, POSTGRES_PASSWORD, SECRET_KEY,
#    SECURITY_PASSWORD_SALT, SKITAK_ADMIN_PASSWORD
nano docker/.env

# 4. Build the dashboard (Nginx serves the static build)
make build-dashboard

# 5. Start the stack
make up

# 6. Watch the logs until healthy, then smoke-test
make logs
make smoke
```

First boot takes a minute or two: OTS runs its database migrations, creates its
certificate authority, and issues the server certificate that Nginx then uses
for HTTPS. Log in at `https://your-server/` as `administrator` with the
password you set in `SKITAK_ADMIN_PASSWORD`.

> The bundled TLS setup uses the OTS CA (self-signed chain). Browsers will
> warn until you either install the CA cert or supply Let's Encrypt
> certificates in `docker/nginx/skitak.conf`.

## Connecting Your First Device

### iTAK / ATAK via invite link (recommended)

1. Create a session and team via the dashboard (or the `/api/skitak` API)
2. Request an invite: `GET /api/skitak/sessions/<id>/teams/<team>/invite` (authenticated)
3. Share the returned `https://server/join/<token>` link with the client
4. On the device the link offers "Open in SkiTAK app" or a TAK data package
   download that iTAK/ATAK imports in one tap — server, certificates, callsign
   and team colour are configured automatically

Invite tokens are single-use and expire after 24 h; a generated package can be
re-downloaded for 2 h in case the first import fails.

### Manual enrollment

The standard OTS flows (certificate enrollment from ATAK/iTAK with username +
password, or admin-generated data packages from the OTS web UI) also work.

## Deployment Targets

### Cloud VPS (recommended for production)

Any 2-core / 4 GB RAM Linux VPS (Hetzner CX22, DigitalOcean Basic, AWS t3.small).

### Raspberry Pi 5 (small groups / on-site)

```bash
make pi
```

Applies memory limits suitable for 4 GB RAM. Connect a travel router to create
a dedicated WiFi hotspot; the Pi acts as both hotspot and server with no
internet. The Meshtastic LoRa gateway is gated behind the `mesh` profile until
the gateway bridge lands (Phase 3).

### Optional profiles

```bash
# Standalone Mumble voice server (no OTS auth integration yet — OTS 1.7.x can
# only reach a Mumble authenticator on localhost)
docker compose --profile voice ... up -d

# MediaMTX video relay — configure stream auth in docker/mediamtx/mediamtx.yml
# BEFORE enabling this on a public host
docker compose --profile video ... up -d
```

## Firewall Rules

```
# Required
TCP 443    — HTTPS (dashboard, API, enrollment)
TCP 8089   — TLS CoT streaming (TAK clients)

# Optional
TCP+UDP 64738 — Mumble voice (voice profile only)

# NOT exposed (internal Docker network only)
TCP 5432   — PostgreSQL
TCP 5672   — RabbitMQ
TCP 8081   — OTS API (Nginx proxies it)
```

## Backup

```bash
# Database dump to backups/
make db-backup

# Also back up the ots_data volume — it holds the CA. Losing it means
# re-enrolling every device.
docker run --rm -v skitak_ots_data:/data -v "$PWD/backups":/backup alpine \
    tar czf /backup/ots-data-$(date +%Y%m%d).tar.gz -C /data .
```

## Updating

```bash
git pull
make build build-dashboard
make up
```

OTS runs its database migrations automatically on startup, and the SkiTAK
plugin applies its own schema changes idempotently.

## Known limitations (Phase 0)

- Mumble/OTS auth integration blocked on upstream (hardcoded localhost Ice address)
- RabbitMQ runs with guest/guest on the internal network only — OTS builds its
  Socket.IO broker URL without credentials
- Client certificates are valid for the OTS CA default lifetime; revocation
  tooling is Phase 1 work
- The React dashboard still targets a placeholder API in places — Phase 1
