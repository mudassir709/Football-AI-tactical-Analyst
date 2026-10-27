# Tactical Eye: Football AI Tactical Analyst

A web platform that turns football match footage into interactive tactical
data. Users upload a broadcast clip; a background AI worker detects and tracks
every player and the ball, maps them onto a 2D pitch, assigns teams, detects
formations and computes tactical metrics. The dashboard draws movement paths,
heatmaps, team shapes and a synchronised 2D tactical board directly over the
video, and an LLM writes a coaching report from the statistics.

![CI/CD](https://github.com/mudassir709/Football-AI-tactical-Analyst/actions/workflows/ci.yml/badge.svg)

## Architecture

```
React dashboard  <--REST / WebSocket-->  Node.js API  --job-->  Redis queue  --job-->  Python AI worker
 (upload, video overlays,                (auth, uploads,                                (detection, tracking,
  2D board, heatmaps, report)             jobs, LLM report)                              homography, teams,
                                              |                                          formations, metrics)
                                              +----------------- PostgreSQL                     |
                                                                                    optional cloud GPU service
```

Heavy video processing never runs inside a web request: the API queues a job
and returns immediately, a worker processes it in the background and reports
progress, and the browser is updated live over a WebSocket. The worker can
offload the computation to a cloud GPU (about 37x faster) and falls back to
local processing when the GPU is unavailable.

## Features

- Upload with progress, two analysis modes (Standard / Quick), live job progress
- Player, goalkeeper, referee and ball detection (YOLOv8) and tracking (ByteTrack)
- Pitch coordinates in metres via per-frame homography from 32 pitch landmarks
- Automatic team assignment from shirt colours (K-Means)
- Formation detection over time (template matching with the Hungarian algorithm)
- Team compactness, width and depth; player distance and speed; heatmaps
- Interactive video overlays and a synchronised 2D tactical board; click a player for their stats
- AI coaching report (Azure OpenAI)
- Accounts with secure sessions; every user sees only their own matches
- Docker images for every service, CI/CD with GitHub Actions, unit tests

## Repository layout

| Folder | Contents |
|---|---|
| `frontend/` | React + TypeScript dashboard (Vite, Tailwind), served by nginx in production |
| `backend/` | Node.js + Express API: authentication, uploads, queue, WebSockets, LLM report (Prisma + PostgreSQL) |
| `worker/` | Python AI pipeline and queue worker; `gpu_server.py` is the optional cloud GPU service |
| `docs/` | Architecture and requirements documents, plus "how it works" notes for every part |
| `docker-compose.yml` | PostgreSQL, Redis and (profile `app`) the three application services |
| `.github/workflows/` | CI/CD pipeline |

## Running it

Requirements: Docker Desktop. Copy `.env.example` to `.env` and fill in the
secrets, and put the two Roboflow model files into `worker/models/`
(`football-player-detection.pt`, `football-pitch-detection.pt`; download links
in `worker/gpu/setup.sh`).

**Everything in containers** (open http://localhost:8080):

```bash
docker compose --profile app up -d --build
```

**Development** (hot reload; Node.js 24 and Python 3.12 needed):

```bash
docker compose up -d                                   # PostgreSQL + Redis
cd backend  && npm install && npx prisma migrate deploy && npm run dev   # API on :4000
cd frontend && npm install && npm run dev               # dashboard on :5173
cd worker   && pip install -r requirements.txt && python worker.py       # AI worker
```

Tests: `cd worker && python -m pytest` (backend/frontend checks: `npm run typecheck`, `npm run lint`, `npm run build`).

## Documentation

| Note | Topic |
|---|---|
| [02-backend-queue-worker](docs/how-it-works/02-backend-queue-worker.md) | API, queue, worker, security, API endpoints |
| [03-frontend](docs/how-it-works/03-frontend.md) | React dashboard, live progress, analysis modes |
| [04-video-overlays](docs/how-it-works/04-video-overlays.md) | Overlays synced to the video, homography projection |
| [05-cloud-gpu](docs/how-it-works/05-cloud-gpu.md) | Cloud GPU service on RunPod, measured speed-up |
| [06-docker-ci-tests](docs/how-it-works/06-docker-ci-tests.md) | Containers, CI/CD, automated tests, AI coaching report |

## Performance

| Job | Laptop CPU (i7-1255U) | Cloud GPU (NVIDIA L4) |
|---|---|---|
| 3 s clip, Quick mode | 44-75 s | 5 s |
| 30 s clip, Standard mode | ~25 min | 40 s |
