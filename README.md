# SkiTAK

**Location-aware comms for outdoor groups.** A TAK-based server stack and thin
iOS client for commercial guiding operations — skiing, trail running,
equestrian, alpine, hiking. Guides see every client live on a map; clients join
a session by tapping a link.

Built on [OpenTAKServer](https://github.com/brian7704/OpenTAKServer) with a
SkiTAK plugin adding sessions, teams, persistent clients, PostGIS track
storage, and zero-friction certificate enrollment.

## Repository layout

| Path | Contents |
|---|---|
| `server/` | SkiTAK OTS plugin (Python, pip-installable) |
| `docker/` | Docker Compose stack: OTS ×3, PostGIS, RabbitMQ, Nginx, tiles |
| `dashboard/` | React + MapLibre guide dashboard |
| `ios/` | SwiftUI native wrapper (background location → CoT) |
| `docs/` | Deployment guide |
| `PLAN.md` | Product thesis and phased development plan |

## Quick start

```bash
make setup                  # create docker/.env — then edit it
make build-dashboard        # build the React app
make up                     # start the stack
make smoke                  # verify API + plugin health
```

See [docs/deployment.md](docs/deployment.md) for details, deployment targets
(cloud VPS, Raspberry Pi, off-grid), and known limitations.
