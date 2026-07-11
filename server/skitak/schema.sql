-- SkiTAK schema — applied idempotently by the plugin at activation.
-- OTS manages its own tables via Flask-Migrate; these are SkiTAK-specific.
-- Requires the postgis extension (created by docker/postgres/init.sql, which
-- runs as the database superuser on first boot).

CREATE TABLE IF NOT EXISTS skitak_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    activity_type   TEXT NOT NULL,           -- skiing, trail_run, equestrian, hiking
    guide_uid       TEXT NOT NULL,           -- TAK UID of the guide
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS skitak_teams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES skitak_sessions(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    color           TEXT DEFAULT 'Cyan',     -- TAK team colour
    role            TEXT DEFAULT 'Team Member'
);

CREATE TABLE IF NOT EXISTS skitak_team_members (
    team_id         UUID REFERENCES skitak_teams(id) ON DELETE CASCADE,
    tak_uid         TEXT NOT NULL,           -- device UID
    callsign        TEXT NOT NULL,
    joined_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (team_id, tak_uid)
);

-- Rich track point storage — one row per GPS sample
CREATE TABLE IF NOT EXISTS skitak_track_points (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID REFERENCES skitak_sessions(id) ON DELETE CASCADE,
    tak_uid         TEXT NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL,
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    altitude_m      REAL,
    speed_ms        REAL,
    course_deg      REAL,
    accuracy_m      REAL,
    -- Biometric fields (populated when available)
    heart_rate_bpm  SMALLINT,
    cadence_rpm     SMALLINT,
    power_watts     SMALLINT,
    -- Device fields
    battery_pct     SMALLINT,
    extra           JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_track_points_session_uid_time
    ON skitak_track_points (session_id, tak_uid, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_track_points_location
    ON skitak_track_points USING GIST (location);

-- Invite tokens for zero-friction onboarding
CREATE TABLE IF NOT EXISTS skitak_invite_tokens (
    token                TEXT PRIMARY KEY,
    session_id           UUID REFERENCES skitak_sessions(id) ON DELETE CASCADE,
    team_id              UUID REFERENCES skitak_teams(id) ON DELETE CASCADE,
    team_name            TEXT NOT NULL,
    team_color           TEXT NOT NULL DEFAULT 'Cyan',
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    expires_at           TIMESTAMPTZ NOT NULL,
    used_at              TIMESTAMPTZ,               -- NULL = not yet used
    -- Set on first package generation; allows re-download for 2h
    callsign             TEXT,
    client_p12_data      BYTEA,
    package_generated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_invite_tokens_expires
    ON skitak_invite_tokens (expires_at);

-- Registered clients (persistent across sessions)
CREATE TABLE IF NOT EXISTS skitak_clients (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name     TEXT NOT NULL,
    callsign         TEXT NOT NULL UNIQUE,
    email            TEXT,
    phone            TEXT,
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ,
    -- Enrollment state
    tak_uid          TEXT,                    -- device UID set when client first connects
    cert_expires_at  TIMESTAMPTZ,
    enrolled_at      TIMESTAMPTZ,
    -- Denormalised stats (updated at session end)
    total_sessions   INTEGER DEFAULT 0,
    total_distance_km REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_clients_callsign ON skitak_clients (callsign);
CREATE INDEX IF NOT EXISTS idx_clients_tak_uid  ON skitak_clients (tak_uid);

-- Link table: which clients are in which session teams
CREATE TABLE IF NOT EXISTS skitak_session_clients (
    session_id   UUID REFERENCES skitak_sessions(id) ON DELETE CASCADE,
    team_id      UUID REFERENCES skitak_teams(id) ON DELETE CASCADE,
    client_id    UUID REFERENCES skitak_clients(id) ON DELETE CASCADE,
    invite_token TEXT,                        -- the token sent to this client for this session
    joined_at    TIMESTAMPTZ,                 -- set when client actually connects
    PRIMARY KEY (session_id, client_id)
);

-- Planned routes — guide uploads a GPX, clients see it on their map
CREATE TABLE IF NOT EXISTS skitak_routes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES skitak_sessions(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    geometry        GEOGRAPHY(LINESTRING, 4326) NOT NULL,
    point_count     INTEGER NOT NULL,
    uploaded_by     TEXT,
    uploaded_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routes_session ON skitak_routes (session_id);

-- POI / waypoints overlay
CREATE TABLE IF NOT EXISTS skitak_pois (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES skitak_sessions(id) ON DELETE CASCADE,
    created_by_uid  TEXT NOT NULL,
    name            TEXT NOT NULL,
    poi_type        TEXT DEFAULT 'waypoint',  -- waypoint, hazard, meetpoint, emergency
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ
);
