# SkiTAK Development Plan

## Product Thesis

> **"Location-aware comms for outdoor groups."**

No existing outdoor app unifies real-time group positioning with contextual messaging. WhatsApp handles comms; Strava handles tracks; nothing connects them. SkiTAK solves this for commercial guiding operations across trail running, equestrian, skiing, alpine, and hiking — where guides need full situational awareness and clients need zero-friction onboarding.

---

## Target Users

| Role | Needs | Technical level |
|------|-------|----------------|
| Guide / operator | See all clients live, manage teams, session history, emergency alerts | Moderate |
| Client | Open app, join session, be tracked, send messages, see guide | Zero — must work in <60 seconds |
| Admin | Manage users, servers, billing (future), export data | High |

---

## Connectivity Model

The architecture must handle all of these gracefully:

| Context | Connectivity | Solution |
|---------|-------------|----------|
| Ski resort | Patchy LTE, WiFi at lifts | Server-connected (cloud or on-site) |
| Alpine / backcountry | No signal | Meshtastic LoRa mesh + local server on carried device |
| Trail running | Variable LTE | Buffer + sync, graceful degradation |
| Equestrian | Often no signal | Mesh SA or LoRa; local Pi server option |

Offline-first is a **Phase 1 requirement**, not a later addition.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                             │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ SkiTAK iOS  │  │ ATAK        │  │  Web Dashboard       │   │
│  │ (thin native│  │ (Android,   │  │  (guide / admin      │   │
│  │  wrapper +  │  │  full ATAK  │  │   post-activity      │   │
│  │  web UI)    │  │  features)  │  │   PWA)               │   │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬───────────┘   │
└─────────┼────────────────┼────────────────────┼───────────────┘
          │ CoT/TLS:8089   │                    │ HTTPS:443
          ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NGINX (reverse proxy / TLS termination)    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────┐   ┌───────────────────────────┐  │
│  │  OpenTAKServer (forked)  │   │  MediaMTX                 │  │
│  │  ├─ CoT router           │   │  (RTSP/RTMP/WebRTC relay) │  │
│  │  ├─ Marti REST API       │   │  Drone + camera feeds     │  │
│  │  ├─ Certificate CA       │   └───────────────────────────┘  │
│  │  ├─ Team/group routing   │                                   │
│  │  └─ SkiTAK extensions   │   ┌───────────────────────────┐  │
│  │     ├─ Session mgmt      │   │  Mumble / Murmur          │  │
│  │     ├─ Track storage     │   │  (PTT voice, OTS auth)    │  │
│  │     ├─ Strava export     │   └───────────────────────────┘  │
│  │     └─ Overlay feeds     │                                   │
│  └──────────────┬───────────┘                                   │
│                 │                                               │
│  ┌──────────────▼───────────┐   ┌───────────────────────────┐  │
│  │  RabbitMQ (message bus)  │   │  PostgreSQL + PostGIS      │  │
│  └──────────────────────────┘   │  Tracks, sessions, users  │  │
│                                 │  Spatial queries           │  │
│                                 └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
          │
          │ (off-grid)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OFFLINE / MESH LAYER                         │
│                                                                 │
│  Meshtastic LoRa nodes ──── TAK-Meshtastic-Gateway             │
│  UDP Multicast Mesh SA (239.2.3.1:6969)                        │
│  Local OTS instance on Raspberry Pi (portable hotspot)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| TAK server core | OpenTAKServer (forked, Python) | Best feature/weight ratio; Python = extensible |
| Message broker | RabbitMQ | Already in OTS; enables horizontal scaling |
| Database | PostgreSQL 16 + PostGIS | Spatial track queries, session history, scalable |
| Reverse proxy | Nginx | TLS termination, static assets, WebSocket proxy |
| Video relay | MediaMTX | RTSP/RTMP/WebRTC; drone + camera feeds |
| Voice | Mumble / Murmur | OTS auth integration built-in; OCB-AES-128 encrypted |
| Deployment | Docker Compose | Single command deploy on any Linux host |
| iOS client | SwiftUI (thin wrapper) + WKWebView | Background location native; UI web-based |
| Web dashboard | React + MapLibre GL | Track replay, session management, guide tools |
| Tile server | mbtileserver | Serve offline map tiles (OS maps, OpenTopoMap, piste maps) |
| Off-grid mesh | Meshtastic + TAK-Meshtastic-Gateway | LoRa bridge for zero-signal environments |
| Strava export | Strava OAuth API | Post-session GPX push |

---

## iOS Client Strategy

iTAK cannot be the primary client for commercial guiding because:
- Non-technical clients cannot configure iTAK themselves
- No background location from a PWA
- No custom onboarding flow

**Solution: Thin native iOS wrapper**

A SwiftUI shell that:
1. Handles background location (native CLLocationManager → CoT UDP/TCP)
2. Provides a WKWebView for the main UI (React web app served from your server)
3. Handles push notifications (APNs)
4. Manages the Mumble connection for PTT
5. Deep links for one-tap session joining (guides share a link, clients tap it)

This means:
- UI development happens once in React (works in browser and in the app)
- Native layer is thin and stable — location, notifications, audio
- No App Store plugin complexity
- ATAK users on Android get full native ATAK experience with the same server

---

## Team / Visibility Model

Maps directly onto TAK's built-in groups system:

```
Admin
  └── Session: "Morning Trail Run - Lake District"
        ├── Team: Guides         (see everyone)
        │     └── Guide Sarah
        ├── Team: Group A        (see each other + guides)
        │     ├── Client Tom
        │     └── Client Emma
        └── Team: Group B        (see each other + guides)
              ├── Client James
              └── Client Lucy
```

Guides see all teams. Teams see within their team and guides only. No custom routing logic needed — OTS group system handles this.

---

## Security Model

- **mTLS on port 8089** — every device has a unique signed certificate
- **HTTPS on port 443** — Nginx proxy with Let's Encrypt or custom CA
- **Ports 8087/8088 closed** — no unencrypted CoT exposed
- **Mumble** — OCB-AES-128, authenticated via OTS user database
- **Client certs** — stored in iOS Keychain (Secure Enclave on modern devices)
- **Onboarding** — one-time deep link generates and installs cert automatically
- **Short cert lifetime** — 90 days, auto-renewed via enrollment API
- **Admin UI** — only accessible via VPN or restricted IP range

---

## Deployment Targets

| Target | Hardware | Users | Use case |
|--------|---------|-------|---------|
| Development | MacBook / Linux VM | 1-5 | Dev and testing |
| Small operation | Raspberry Pi 5 (4GB) | up to 30 | Single guide, local |
| Cloud (primary) | 2-core VPS, 4GB RAM | up to 200 | Commercial SaaS |
| Off-grid portable | Raspberry Pi 5 + LoRa HAT + battery | 10-20 | Backcountry, no signal |

`docker compose up` targets all except off-grid (which gets a separate Pi image).

---

## Phased Development Plan

### Phase 1 — Foundation (6–8 weeks)
*Goal: A working server that guides and clients can actually use in the field.*

**Server**
- [ ] Fork OpenTAKServer into this repo under `/server`
- [ ] Replace SQLite with PostgreSQL + PostGIS (SQLAlchemy config change + schema migration)
- [ ] Docker Compose: OTS + PostgreSQL + RabbitMQ + Nginx + Mumble + MediaMTX
- [ ] Automated CA + cert generation on first boot
- [ ] One-command deep link enrollment (client taps link → cert installed → tracking starts)
- [ ] Firewall config: close 8087/8088, expose only 8089 and 443

**iOS**
- [ ] Thin SwiftUI wrapper app
  - Background CLLocationManager → CoT TCP stream to server
  - WKWebView loading the web dashboard
  - Push notification handling (APNs)
  - Deep link handler for session join URLs
- [ ] TestFlight distribution for beta

**Web Dashboard (Guide view)**
- [ ] Live map (MapLibre GL) showing all connected team members
- [ ] Team assignment UI
- [ ] Session creation (name, date, invite link generation)
- [ ] Basic GeoChat view

**Offline map tiles**
- [ ] mbtileserver container serving OS maps / OpenTopoMap tiles
- [ ] Tile cache pre-load on iOS app install for home region

**Verification**
- [ ] Guide on web dashboard sees all clients live
- [ ] iOS client tracks in background with screen locked
- [ ] ATAK (Android) connects and works identically
- [ ] GeoChat messages appear on all devices
- [ ] Voice PTT works via Mumble (separate Mumble app on iOS for now)
- [ ] Emergency beacon alerts guide immediately

---

### Phase 2 — Outdoor Features (6–8 weeks)
*Goal: Features that make this better than WhatsApp + Strava for guides.*

**Track recording and analysis**
- [ ] Rich track storage: GPS + timestamp + speed + elevation per point (PostGIS LineString)
- [ ] Session summary: distance, elevation gain, duration, max speed, map
- [ ] Track replay (scrub through the session on the web dashboard)
- [ ] GPX export per client per session
- [ ] Strava OAuth integration — one-tap push to Strava after session

**Guide tools**
- [ ] Session dashboard: client list, battery levels, last seen, connection status
- [ ] Historical sessions: browse past sessions, compare tracks
- [ ] Client profile: session history, total distance, regular routes
- [ ] Route pre-load: guide uploads a planned route (GPX/KMZ), clients see it on their map

**Map overlays (server-pushed)**
- [ ] Weather overlay (Met Office / OpenWeatherMap API → CoT overlay events)
- [ ] Avalanche warning overlay for alpine sessions (avalanche.org / national services)
- [ ] Custom POI management (guide marks waypoints: meeting points, hazards, toilets)

**Equestrian-specific**
- [ ] Horse + rider pair tracking (one CoT UID per horse)
- [ ] Pace/speed display calibrated for walk/trot/canter/gallop
- [ ] Paddock/arena boundary geofence alerts

**iOS improvements**
- [ ] Native PTT button in iOS wrapper (WebRTC or Mumble protocol direct)
- [ ] Offline tile cache management UI
- [ ] Location accuracy and battery mode settings (high accuracy vs power saving)

---

### Phase 3 — Integrations & Scale (ongoing)
*Goal: Connect the ecosystem and make commercial operation viable.*

**Exercise tracker integrations**
- [ ] Garmin Connect webhook → session data overlay
- [ ] Wahoo ELEMNT → live power/HR data in CoT detail fields
- [ ] Apple HealthKit (iOS wrapper) → HR displayed on guide dashboard per client
- [ ] Post-session sync: push completed track to Garmin Connect

**Off-grid / mesh**
- [ ] Meshtastic LoRa gateway (TAK-Meshtastic-Gateway) in Docker Compose
- [ ] Portable Pi image: OTS + Meshtastic + local WiFi hotspot (plug in, switch on)
- [ ] Graceful sync: buffer CoT events offline, sync to cloud server when signal returns

**Drone and camera**
- [ ] RTSP stream registration UI (guide adds drone feed URL)
- [ ] Drone position CoT (MAVLink → CoT bridge via PyTAK)
- [ ] Clients see drone video feed in app

**Commercial infrastructure (if going SaaS)**
- [ ] Multi-tenant: each operator gets isolated teams, sessions, storage
- [ ] Operator onboarding flow (sign up → server provisioned → guide account created)
- [ ] Usage billing hooks (sessions, connected clients, storage)
- [ ] GDPR: data retention policy, client data export, right to deletion

**Satellite integration**
- [ ] Garmin inReach API → position CoT events (for truly off-grid users)
- [ ] SPOT API integration

---

## Repository Structure

```
SkiTAK/
├── server/                    # Forked + extended OpenTAKServer
│   ├── opentakserver/         # Core OTS (upstream fork)
│   └── skitak/                # SkiTAK extensions module
│       ├── sessions.py        # Session management
│       ├── tracks.py          # PostGIS track storage
│       ├── overlays.py        # Weather/hazard overlay feeds
│       ├── export.py          # GPX, Strava export
│       └── equestrian.py      # Equestrian-specific logic
├── docker/
│   ├── docker-compose.yml     # Full stack
│   ├── docker-compose.dev.yml # Dev overrides
│   ├── docker-compose.pi.yml  # Raspberry Pi / off-grid variant
│   └── nginx/
│       └── skitak.conf
├── dashboard/                 # React web app (guide + admin UI)
│   ├── src/
│   │   ├── map/               # MapLibre GL live map
│   │   ├── sessions/          # Session management
│   │   ├── tracks/            # Track replay and analysis
│   │   └── admin/             # User, team, cert management
│   └── public/
├── ios/                       # SwiftUI native wrapper
│   ├── SkiTAK/
│   │   ├── Location/          # CLLocationManager → CoT
│   │   ├── WebView/           # WKWebView shell
│   │   ├── PTT/               # Push-to-talk audio
│   │   └── Notifications/     # APNs handler
│   └── SkiTAK.xcodeproj
├── integrations/              # PyTAK-based bridges
│   ├── weather/               # Met Office → CoT overlay
│   ├── avalanche/             # Avalanche warnings → CoT
│   ├── garmin/                # inReach API → CoT
│   └── mavlink/               # Drone telemetry → CoT
├── maps/                      # Offline map packaging scripts
│   ├── download_os.sh         # OS maps tile download
│   ├── download_piste.sh      # OpenSnowMap tiles
│   └── package_mbtiles.sh     # Package for distribution
└── docs/
    ├── architecture.md
    ├── deployment.md
    └── onboarding.md
```

---

## Key Design Decisions (Locked)

| Decision | Choice | Reason |
|----------|--------|--------|
| Server base | Fork OpenTAKServer | Best Python TAK implementation; avoids reinventing CoT routing |
| Database | PostgreSQL + PostGIS | Spatial track queries non-negotiable for post-activity features |
| iOS client | Thin native wrapper | Background location + zero-friction onboarding impossible with iTAK or PWA alone |
| UI approach | React web app in WKWebView | Build once, works in browser (guide dashboard) and in app |
| Offline | Meshtastic LoRa + local Pi | Equestrian and backcountry users have no signal |
| Voice | Mumble via OTS auth | Lowest complexity path to encrypted PTT |
| Deployment | Docker Compose | Single command, portable, Pi-compatible |
| Multi-tenant | Design for it Phase 1, build it Phase 3 | Keeps SaaS option open without over-engineering now |

---

## What is Not Being Built

- A full replacement for ATAK (the server + thin iOS app is the product)
- Navigation / turn-by-turn directions (defer to Komoot integration)
- Social features (public activity feed, followers) — Strava handles this
- Full incident management system (emergency beacon sufficient for Phase 1)
- Federation between SkiTAK instances (not needed until multi-operator)
- An Android app (ATAK is the Android client)

---

## Immediate Next Steps

1. Set up Docker Compose with OTS + PostgreSQL + Nginx (skeleton, no custom code yet)
2. Verify iTAK and ATAK connect and track correctly against the base server
3. Scaffold the React dashboard with a live MapLibre map showing connected clients
4. Begin SwiftUI iOS wrapper — background location to CoT is the critical path
5. Set up mbtileserver with OpenTopoMap tiles as proof of concept
