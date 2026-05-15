# SkiTAK Deployment Guide

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A domain name pointing to your server (for production TLS)
- Ports open: `443`, `8089`, `64738` (TCP+UDP for Mumble)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/Sheer-elbow/SkiTAK
cd SkiTAK

# 2. Run setup (creates docker/.env from template)
make setup

# 3. Edit your environment — at minimum set these:
#    SERVER_HOSTNAME, POSTGRES_PASSWORD, RABBITMQ_PASSWORD,
#    OTS_SECRET_KEY, OTS_ADMIN_PASSWORD
nano docker/.env

# 4. Start the stack
make up

# 5. Watch the logs until healthy
make logs
```

The server is ready when you see `opentakserver` report `Listening on :8089`.

## Connecting Your First Device

### iTAK / ATAK (recommended)

1. In the admin UI (`https://your-server/`), go to **Users → New User**
2. Set a callsign and password
3. Click **Generate Enrollment Package** — downloads a `.zip`
4. On the device: open iTAK → Import → select the `.zip`
5. The server connection, certificates, and map sources are configured automatically

### Deep Link (for clients — zero friction)

1. Create a session in the guide dashboard
2. Add teams, set team colours
3. Click **Invite** on a team → copy the link
4. Share the link via WhatsApp/AirDrop/SMS to clients
5. Client taps the link → SkiTAK iOS app opens → certificate installed → tracking starts

## Deployment Targets

### Cloud VPS (recommended for production)

Any 2-core / 4 GB RAM Linux VPS (Hetzner CX22, DigitalOcean Basic, AWS t3.small).

Set `SSL_MODE=letsencrypt` in `.env` and ensure port 80 is open for ACME challenge.

### Raspberry Pi 5 (small groups / on-site)

```bash
make pi
```

Uses `docker-compose.pi.yml` which:
- Sets memory limits appropriate for 4 GB RAM
- Enables mesh SA multicast for local WiFi
- Optionally enables Meshtastic LoRa gateway

Connect a TP-Link travel router to create a dedicated WiFi hotspot.
The Pi acts as both hotspot and server — works with no internet.

### Off-grid / Backcountry

Same as Pi setup, plus a Meshtastic LoRa radio on `/dev/ttyUSB0`.

```bash
MESHTASTIC_PORT=/dev/ttyUSB0 make pi
```

Position updates flow: device → LoRa radio → Meshtastic gateway → OTS → all connected devices.

## Firewall Rules

```
# Required
TCP 443    — HTTPS (web dashboard + Marti API)
TCP 8089   — TLS CoT streaming (TAK clients)
TCP+UDP 64738 — Mumble voice

# NOT exposed (internal Docker network only)
TCP 5432   — PostgreSQL
TCP 5672   — RabbitMQ
TCP 8080   — OTS internal API
TCP 8088   — Unencrypted CoT (never expose)
```

## Backup

```bash
# Daily database backup
make db-backup

# To restore
docker compose exec -T postgres psql -U skitak skitak < backups/skitak-YYYYMMDD.dump
```

## Updating

```bash
git pull
make build
make up
```

OTS runs database migrations automatically on startup.
