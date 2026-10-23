# How it works: backend, queue and AI worker

This note explains the platform's server side in plain language, for anyone
new to Node.js, Docker or job queues.

## The big picture

```
Browser ──HTTP──▶ Node.js API ──adds job──▶ Redis queue ──job──▶ Python AI worker
   ▲                  │  ▲                                          │
   │                  ▼  └──────── progress / completed events ─────┘
   └──WebSocket── PostgreSQL (users, matches, summaries)
                     storage/ (videos, results JSON)
```

1. The user uploads a video. The **API** saves the file, creates a `Match` row
   with status `QUEUED`, adds a job to the **queue**, and answers immediately.
2. The **worker** takes the job, runs the AI pipeline, and reports progress
   ("Detecting and tracking players, 40 %") through the queue.
3. The API listens to those queue events, updates the database, and pushes
   each update to the user's browser over a **WebSocket**.
4. When the worker finishes, it writes a results file (every player position,
   heatmaps, formations, metrics) and the match becomes `COMPLETED`.

**Why not analyse the video inside the upload request?** Analysis takes
minutes. A web request that runs that long would time out, freeze the server
for other users, and lose all work if anything crashed. With a queue, the API
stays fast, jobs survive restarts, failed jobs are retried, and more workers
can be added to process several videos at once.

## The pieces

| Piece | Technology | Role |
|---|---|---|
| Database | PostgreSQL (in Docker) | Users, matches, status, summary numbers |
| Queue | Redis (in Docker) + BullMQ | Holds jobs; carries progress events |
| API | Node.js, Express, TypeScript | Login, uploads, match data, WebSockets |
| ORM | Prisma | Typed database access from TypeScript |
| Worker | Python, BullMQ for Python | Runs `worker/src/pipeline.py` per job |
| File storage | `storage/` folder | `videos/` (uploads and their H.264 playback copies) and `results/` (analysis JSON) |

**Why a playback copy?** Browsers only play a few video codecs reliably.
Uploads can be HEVC from phones, old MPEG-4, AVI and more, so the worker's
first step re-encodes every upload to H.264 MP4 (`videos/<id>_web.mp4`),
frame for frame at the same frame rate so the analysis overlays stay in sync.
The video player always streams this copy.

## Security measures

- **Passwords** are hashed with bcrypt (cost 12); the plain password is never stored.
- **Sessions** use a signed JWT in an HTTP-only cookie, so page scripts cannot steal it.
- **Login errors** are identical for unknown email and wrong password, so the
  form cannot be used to discover registered emails.
- **Ownership**: every match query filters by the logged-in user; other users'
  matches return 404, so their IDs cannot even be confirmed to exist.
- **Uploads**: extension and MIME type are checked, and then the file's first
  bytes ("magic numbers") must match a real video container (MP4/MOV, MKV/WebM
  or AVI). Files are saved under random names, never the user's filename.
- **Paths**: stored paths are relative and both services refuse any path that
  points outside the storage folder.
- **Secrets** (database password, JWT secret, API keys) live in `.env`, which
  Git never commits.

## Running it locally

```bash
# 1. Database and queue (once; they keep running in the background)
docker compose up -d

# 2. API  (terminal 1)
cd backend
npm install          # first time only
npm run dev          # http://localhost:4000

# 3. AI worker  (terminal 2)
cd worker
..\venv\Scripts\python worker.py
```

Check everything is connected: open http://localhost:4000/api/health. It
reports the database, Redis, the number of connected workers and the job counts.

## API endpoints

| Method | Path | What it does |
|---|---|---|
| POST | `/api/auth/register` | Create an account (email, name, password) |
| POST | `/api/auth/login` | Log in; sets the session cookie |
| POST | `/api/auth/logout` | Log out |
| GET | `/api/auth/me` | Who is logged in |
| POST | `/api/matches` | Upload a video (form field `video`, optional `title`) |
| GET | `/api/matches` | List my matches |
| GET | `/api/matches/:id` | One match, including summary numbers |
| GET | `/api/matches/:id/video` | Stream the video (supports seeking) |
| GET | `/api/matches/:id/results` | Full analysis JSON for the dashboard |
| DELETE | `/api/matches/:id` | Delete a match and its files |
| GET | `/api/health` | Service health for monitoring |

WebSocket event `match:updated` is pushed to the owner whenever a match's
status or progress changes.

## Likely committee questions

**Why both Node.js and Python?** Each does what it is best at: Node.js handles
many simultaneous web connections efficiently; Python has the computer-vision
ecosystem (PyTorch, Ultralytics, OpenCV). The queue lets them cooperate
without either depending on the other's language.

**What happens if the worker crashes during a job?** The job's lock in Redis
expires, BullMQ moves it back to the queue, and a worker processes it again.
Jobs are also retried once automatically after an error.

**How would it scale?** Start more worker processes or containers; each takes
jobs from the same queue. The API does not change.

**Why store results as files instead of in the database?** A 30-second clip
produces hundreds of thousands of numbers. The database keeps what is queried
and listed (status, owner, summary); the bulky frame-by-frame data is a file
the browser downloads once.
