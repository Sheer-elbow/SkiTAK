# skitak — OpenTAKServer plugin

SkiTAK's server-side extensions, packaged as an [OpenTAKServer](https://github.com/brian7704/OpenTAKServer)
plugin. OTS discovers it through the `opentakserver.plugin` entry point and registers its
blueprints at startup:

- `/api/skitak/sessions` — session and team management (guide-only, authenticated)
- `/api/skitak/clients` — persistent client roster (guide-only, authenticated)
- `/api/skitak/enroll/<token>` — invite-token enrollment (native app JSON + iTAK/ATAK data package)
- `/join/<token>` — invite landing page

## Install

```bash
pip install opentakserver==1.7.11
pip install .
```

The plugin applies its own (idempotent) database schema at activation. It requires
PostgreSQL with PostGIS — see `skitak/schema.sql`.

## Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `SKITAK_SERVER_ADDRESS` | Public hostname baked into enrollment packages (falls back to the request host) |
| `SKITAK_ADMIN_PASSWORD` | If set, replaces OTS's default `administrator`/`password` credentials on startup |
