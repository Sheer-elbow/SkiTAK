-- Runs once on first database init, as the PostgreSQL superuser.
-- Only extension setup lives here — the SkiTAK tables are applied
-- idempotently by the plugin at startup (server/skitak/schema.sql),
-- so schema changes reach existing deployments too.
CREATE EXTENSION IF NOT EXISTS postgis;
