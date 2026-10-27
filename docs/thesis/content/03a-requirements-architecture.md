# Developer Documentation

This chapter documents the design and implementation of Tactical Eye for developers who want to understand, maintain or extend it. It starts with the requirements, then presents the architecture, deployment, data model and algorithms, describes each service module by module, and closes with the testing of the system. The source code is organised in three folders, one per service: `frontend/` (React dashboard), `backend/` (Node.js API) and `worker/` (Python AI worker), plus `docker-compose.yml` and the CI/CD workflow in `.github/workflows/`.

## Requirements specification

### Functional requirements

Table: Functional requirements {widths=10,62,28}
| ID | Requirement | Realised in |
|---|---|---|
| F1 | Users can register with name, e-mail and password, log in and log out; sessions persist across browser restarts for 7 days. | `routes/auth.ts`, `AuthPage` |
| F2 | Users can upload a match video (MP4, MOV, M4V, MKV, WebM, AVI, up to 500 MB) with a title and an analysis mode, and see the upload progress. | `routes/matches.ts`, `UploadPage` |
| F3 | Uploads are analysed asynchronously by AI workers through a job queue; the web request returns immediately. | `queue.ts`, `worker.py` |
| F4 | The progress of each analysis (percentage and step) is shown live without reloading the page. | Socket.IO, `useMatchUpdates` |
| F5 | The system detects and tracks players, goalkeepers, referees and the ball. | `detector.py`, `tracker.py` |
| F6 | Positions are converted from image pixels to pitch coordinates in metres. | `homography.py` |
| F7 | Players are assigned to two teams automatically; goalkeepers to their team. | `clustering.py` |
| F8 | Each team's formation is recognised over time and formation changes are reported. | `clustering.py` |
| F9 | The system computes team compactness, width, depth, player distance and speed, and heatmaps of teams, players and ball. | `metrics.py` |
| F10 | Results are shown as overlays on the video (players, movement paths, team shape, ball, heatmaps), synchronised frame by frame. | `VideoAnalysis`, `draw.ts` |
| F11 | A 2D tactical board shows the same moment from above; formations of the current moment are displayed. | `drawBoard`, `VideoAnalysis` |
| F12 | Clicking a player shows their path, heatmap, distance, time visible and speeds. | `PlayerPanel` |
| F13 | An LLM generates a coaching report from the computed statistics; the report is stored. | `report.ts`, `CoachingReport` |
| F14 | Users can list, re-analyse and delete their own matches; they cannot access other users' matches. | `routes/matches.ts` |
| F15 | Analysis can optionally run on a remote GPU service, with automatic fallback to local analysis. | `remote.py`, `gpu_server.py` |

### Non-functional requirements

Table: Non-functional requirements {widths=10,22,68}
| ID | Quality | Requirement |
|---|---|---|
| N1 | Responsiveness | No web request waits for an analysis; heavy work runs in workers. The dashboard stays usable during analysis. |
| N2 | Scalability | Analysis capacity can be increased by adding workers or using a GPU, without changing the API or the dashboard. |
| N3 | Reliability | A failed or crashed analysis is retried; partial results are never shown; a lost GPU service falls back to local analysis. |
| N4 | Security | Passwords are hashed; sessions are protected against script access; uploads are validated; users are isolated from each other; secrets are kept out of the repository. |
| N5 | Deployability | The whole platform starts with one command; every service has a container image; images are built and published automatically. |
| N6 | Maintainability | Typed code (TypeScript, Python type hints), validation of all external input, automated tests and checks on every change. |
| N7 | Usability | Overlays are synchronised to the exact video frame; the dashboard works in current browsers and adapts to smaller screens. |
| N8 | Efficiency | Long videos are streamed, never held in memory; the AI models are loaded once per worker process. |

### Use cases

Figure 3.1 shows the actors and their use cases. The **registered user** is the main actor. The **AI worker** is a system actor: it is not a person, but it initiates the analysis and progress use cases. The **operator** deploys and configures the system outside the dashboard.

![Use case diagram](figures/usecase.png){w=15}

Table: User stories for the main use cases {widths=22,78}
| Use case | User story |
|---|---|
| Upload a match | *Given* a logged-in user with a video file, *when* they choose the file, a title and a mode and click Upload and analyse, *then* the video is stored, a match appears with status Queued and its page opens. |
| Follow progress | *Given* a match being analysed, *when* the worker finishes a step, *then* the progress bar and step label update on every open page of that user within a second, without reloading. |
| Watch the analysis | *Given* a finished match, *when* the user plays the video, *then* markers, paths and shapes stay on the players in every frame, also while the camera pans, and the board shows the same moment. |
| Inspect a player | *Given* the analysis page, *when* the user clicks a player on the video or the board, *then* the player is highlighted and their heatmap, path, distance and speeds are shown. |
| Generate a report | *Given* a finished match and a configured LLM, *when* the user clicks Generate report, *then* a Markdown report based only on the statistics is shown and stored. |
| Retry after failure | *Given* a worker that crashes during a job, *when* its job lock expires, *then* the job is given to a worker again; after a second failure the match is shown as Failed with the reason. |

## System architecture

### Overview

Tactical Eye follows a distributed, service-oriented architecture with an asynchronous job queue (Figure 3.2). It separates three concerns that have very different resource profiles:

- the **presentation tier**, the React single-page application in the browser, which renders the dashboard and the overlays;
- the **application tier**, the Node.js API, which handles many short requests (authentication, uploads, listing, streaming, live updates) and must stay responsive;
- the **processing tier**, the Python AI workers, which perform long, CPU- or GPU-bound computations, one job at a time.

The tiers communicate through well-defined interfaces: REST and WebSocket between browser and API, a Redis-backed **BullMQ** queue [13] between API and workers, a shared file storage for videos and results, and the PostgreSQL database [15] owned by the API.

![Component architecture and communication paths](figures/architecture.png){w=12.5}

The key design decision is that **the API never runs the analysis itself**. Uploading a match creates a database row and a queue job, and the request returns immediately. Workers pull jobs from the queue whenever they are free. This decouples the two sides: the API can serve hundreds of users while a worker spends 25 minutes on one video, workers can be added or removed without the API noticing, a worker crash does not affect the API, and jobs survive restarts because they are stored in Redis.

Progress flows in the opposite direction: the worker reports progress to the queue, the queue emits events, and the API, which listens to these events, updates the database and pushes the change to the browser over Socket.IO [14]. The browser never polls.

### Technologies

Table: Technologies and versions {widths=18,30,52}
| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React 19, TypeScript 6 | Component-based user interface [10]. |
| | Vite 8 | Development server and production bundler [27]. |
| | React Router 8 | Client-side routing between pages. |
| | Tailwind CSS 4 | Utility-first styling, responsive layout [26]. |
| | Socket.IO client 4.8 | Live match updates. |
| | react-markdown 10 | Rendering the coaching report. |
| | HTML5 Canvas, `requestVideoFrameCallback` | Frame-synchronised overlay drawing. |
| Backend | Node.js 24, Express 5, TypeScript 6 | REST API [11]; Express 5 forwards errors of async handlers to the error middleware. |
| | Prisma 7 with PostgreSQL 17 | Typed database access and migrations [12]. |
| | BullMQ 6 on Redis 7.4 | Job queue and queue events [13], [16]. |
| | Socket.IO 4.8 | WebSocket server. |
| | Zod 4 | Validation of request bodies and configuration. |
| | Multer 2, bcryptjs 3, jsonwebtoken 9 | Uploads, password hashing, session tokens. |
| | openai 6 (AzureOpenAI client) | Coaching report generation [20]. |
| AI worker | Python 3.12 | Worker language. |
| | Ultralytics 8.4 (YOLOv8), PyTorch 2.14 | Object and keypoint detection [1], [29]. |
| | trackers 2.6 (ByteTrack), supervision 0.31 | Multi-object tracking, detection utilities [2], [24]. |
| | OpenCV 5, NumPy 2.5, pandas 3, SciPy 1.18, scikit-learn 1.9 | Homography, colour spaces, data processing, Hungarian algorithm, convex hulls, K-Means [22], [23]. |
| | PyAV 19 (libx264) | Browser-compatible video encoding. |
| | bullmq 3.4 (Python) | Queue consumer compatible with the Node.js BullMQ. |
| | FastAPI, uvicorn, httpx | Remote GPU service and its client. |
| Operations | Docker, Docker Compose, nginx 1.27 | Containers, orchestration, reverse proxy [17]. |
| | GitHub Actions, GitHub Container Registry | CI/CD pipeline, image registry [18]. |
| | Azure OpenAI (gpt-5-mini), RunPod (NVIDIA L4) | External LLM and GPU services. |

TypeScript was chosen for the frontend and the API because static types catch whole classes of errors (misspelt fields, missing null checks) before the code runs, and the same language on both sides keeps shared data shapes consistent. Python was chosen for the worker because the computer vision and data science ecosystem (PyTorch, OpenCV, pandas, SciPy) is centred on it. BullMQ has compatible Node.js and Python implementations, which allows the two languages to share one queue.

### Layers inside the services

Each service is internally layered as well:

- **Frontend**: *pages* (one per route) compose reusable *components*; all server communication goes through one API module (`api.ts`) and one WebSocket hook (`useMatchUpdates`); pure *analysis* modules (`timeline.ts`, `geometry.ts`, `draw.ts`) contain the overlay logic and have no dependency on React.
- **Backend**: *routes* (HTTP handling, input validation) call *service modules* (`queue.ts`, `storage.ts`, `report.ts`, `auth.ts`), which use the *data access* layer (Prisma client in `db.ts`). `config.ts` validates all settings at start-up; `matchView.ts` defines the public representation of a match.
- **Worker**: the *queue adapter* (`worker.py`) knows nothing about computer vision; it calls the *pipeline orchestrator* (`pipeline.py`), which chains independent *stage modules* (detection, tracking, homography, clustering, trajectories, metrics, transcoding) that only exchange pandas DataFrames.

### End-to-end flow

Figure 3.3 shows the complete life of an upload as a sequence diagram: the upload is validated and stored, a job is queued, the worker reports progress which is relayed to the browser, and on completion the browser downloads the results and the playback video.

![Sequence of an upload, its analysis and the live updates](figures/sequence_upload.png){w=15.5}

## Deployment and component plan

### Containers

Every service has its own `Dockerfile`, and `docker-compose.yml` describes how the containers work together (Figure 3.4). The file uses a Compose *profile*: `docker compose up -d` starts only PostgreSQL and Redis, which is convenient during development when the three application services run directly on the developer's machine with hot reloading; `docker compose --profile app up -d --build` starts the whole platform.

![Deployment diagram](figures/deployment.png){w=14}

Table: Container images {widths=14,26,60}
| Service | Base image | Build and start-up |
|---|---|---|
| frontend | `node:24-alpine` → `nginx:1.27-alpine` | Multi-stage build: the first stage runs `npm ci` and `npm run build`; only the static output is copied into the small nginx image. |
| backend | `node:24-alpine` | `npm ci`, `prisma generate`; on start `prisma migrate deploy` applies pending database migrations, then the API starts. Health check: `wget` on `/api/health`. |
| worker | `python:3.12-slim` | Installs OpenCV's system libraries, the CPU build of PyTorch and the pinned requirements. The models are mounted read-only from `worker/models`, so the image (about 3.4 GB) contains no large model files and the CI pipeline needs none. |
| postgres | `postgres:17-alpine` | Data in a named volume; health check with `pg_isready`. |
| redis | `redis:7.4-alpine` | Queue storage with the append-only file enabled, so queued jobs survive a Redis restart; health check with `redis-cli ping`. |

The backend and worker containers mount the same `./storage` folder at `/storage`. The database stores only **relative** paths (for example `videos/3f2a….mp4`), and each service joins them with its own `STORAGE_DIR`, so the services agree on files even though they see the folder at different absolute paths. Containers declare `depends_on` with health conditions, so the backend only starts when the database and Redis are ready.

### Reverse proxy

In the container deployment the browser talks only to nginx on port 8080. nginx serves the built dashboard and forwards `/api/` and `/socket.io/` to the backend container (Listing 3.1). Because everything is served from one origin, the login cookie and the WebSocket work without cross-origin configuration. Uploads are streamed straight through (`proxy_request_buffering off`) and the body limit matches the API's 500 MB limit. Unknown paths such as `/matches/abc` return `index.html`, so deep links into the single-page application work.

Listing: nginx configuration (excerpt from frontend/nginx.conf)
```
client_max_body_size 520m;

location /api/ {
    proxy_pass http://backend:4000;
    proxy_request_buffering off;  # stream uploads straight to the API
    proxy_read_timeout 300s;
}
location /socket.io/ {
    proxy_pass http://backend:4000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;  # WebSocket handshake
    proxy_set_header Connection "upgrade";
}
location / {
    try_files $uri $uri/ /index.html;       # single-page app fallback
}
```

### Continuous integration and delivery

The GitHub Actions workflow `.github/workflows/ci.yml` runs on every push and pull request (Figure 3.5). Three jobs run in parallel: the **backend** job installs the dependencies, generates the Prisma client and type-checks the code; the **frontend** job lints the code with oxlint and builds the production bundle (which includes the TypeScript check); the **worker** job installs the CPU build of PyTorch and runs the unit tests with pytest. Only if all three succeed does the **images** job build the three Docker images in a build matrix. On pushes to `main` the images are also published to the GitHub Container Registry, tagged with `latest` and the commit hash, so every published image is a tested one and any earlier version can be redeployed.

![CI/CD pipeline](figures/cicd.png){w=15.5}

### Configuration

All settings come from environment variables (Table 2.4). Locally they are read from the `.env` file at the repository root; in Docker, Compose passes them to the containers. The API validates its configuration with a Zod schema at start-up (Listing 3.2), so a missing or malformed value stops the server immediately with a clear message instead of failing later inside a request. Secrets (`JWT_SECRET`, database password, GPU token, Azure key) exist only in `.env`, which is excluded from version control.

Listing: Validated configuration (excerpt from backend/src/config.ts)
```
const EnvSchema = z.object({
  DATABASE_URL: z.string().min(1),
  REDIS_URL: z.string().default("redis://localhost:6379"),
  JWT_SECRET: z.string().min(32, "JWT_SECRET must be at least 32 characters"),
  MAX_UPLOAD_MB: z.coerce.number().positive().default(500),
  COOKIE_SECURE: z.enum(["true", "false"]).optional(),
});
const parsed = EnvSchema.safeParse(process.env);
if (!parsed.success) {
  console.error("Invalid configuration:\n" + z.prettifyError(parsed.error));
  process.exit(1);
}
```
