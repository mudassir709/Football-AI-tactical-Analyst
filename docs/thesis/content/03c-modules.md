## The backend (API)

### Module structure

The API (`backend/src/`) is an Express 5 application written in TypeScript and executed with `tsx`. Table 3.11 lists its modules with their responsibilities.

Table: Modules of the API {widths=22,78}
| Module | Responsibility |
|---|---|
| `index.ts` | Entry point: creates the HTTP server and the Socket.IO server on the same port, authenticates WebSocket connections, starts the queue event listener and shuts everything down cleanly on SIGINT/SIGTERM. |
| `app.ts` | Builds the Express application: CORS, JSON body parser (1 MB limit), cookie parser, the routers, the health endpoint, the 404 handler for unknown API paths and the central error handler. |
| `config.ts` | Loads `.env`, validates all settings with Zod, exposes a typed `config` object. |
| `db.ts` | The single shared Prisma client (PostgreSQL driver adapter). |
| `auth.ts` | Signing and verifying session tokens, cookie options, the `requireAuth` middleware. |
| `routes/auth.ts` | `/api/auth/*`: register, login, logout, current user. |
| `routes/matches.ts` | `/api/matches/*`: upload, list, get, video streaming, results, re-analyse, report, delete. |
| `queue.ts` | The BullMQ queue, job creation and removal, worker counting, and the listener that turns queue events into database updates. |
| `storage.ts` | Storage folders, safe resolution of stored paths, file deletion, video signature check. |
| `report.ts` | Builds the statistics for the LLM, calls Azure OpenAI and translates its errors. |
| `matchView.ts` | `toPublicMatch()`: the representation of a match sent to browsers (no internal file paths, `hasReport` flag instead of the report text). |

### REST API

All endpoints are under `/api` and exchange JSON (except uploads and file downloads). Errors always have the form `{"error": "message"}` with a suitable HTTP status code. All match endpoints require a valid session cookie.

Table: REST endpoints {widths=11,30,59}
| Method | Path | Description and responses |
|---|---|---|
| POST | `/auth/register` | Body `{name, email, password}`. Creates the user, sets the session cookie. 201; 400 invalid input; 409 e-mail exists. |
| POST | `/auth/login` | Body `{email, password}`. Sets the session cookie. 200 `{user}`; 401 wrong credentials. |
| POST | `/auth/logout` | Clears the cookie. 204. |
| GET | `/auth/me` | The logged-in user. 200 `{user}`; 401 not logged in or account deleted. |
| POST | `/matches` | Multipart form with `video`, `title`, `mode`. Stores the file, creates the match, queues the job. 201 `{match}`; 400 no/invalid file; 413 too large. |
| GET | `/matches` | The user's matches, newest first. 200 `{matches}`. |
| GET | `/matches/:id` | One match. 200 `{match}`; 404 not found or not owned. |
| GET | `/matches/:id/video` | Streams the playback copy (or the original), with HTTP Range support for seeking. 200/206. |
| GET | `/matches/:id/results` | The results file. 200; 409 not finished. |
| POST | `/matches/:id/reanalyse` | Optional body `{mode}`. Queues the analysis again. 200 `{match}`; 409 already queued or running. |
| GET | `/matches/:id/report` | 200 `{report, enabled}`; `enabled` tells the dashboard whether reports are configured. |
| POST | `/matches/:id/report` | Generates and stores the report. 200 `{report}`; 409 not finished; 429/502/503 report service errors. |
| DELETE | `/matches/:id` | Deletes the match, its job (if waiting) and its files. 204; 409 while processing. |
| GET | `/health` | Database, Redis, number of workers and job counts. 200 when healthy, 503 otherwise. |

The **WebSocket** interface has a single event. After connecting, the server places each socket in a private room `user:<id>`; whenever one of the user's matches changes, the server emits `match:updated` with the public match object to that room only.

### Important functions

Table: Important functions of the API {widths=24,26,50}
| Function | Input → output | Action |
|---|---|---|
| `requireAuth` (auth.ts) | request → `req.userId` or 401 | Reads the `token` cookie, verifies the JWT signature and expiry, attaches the user ID. |
| `signToken` / `verifyToken` | user ID ↔ JWT | HS256-signed token with the user ID as subject, valid for 7 days [21]. |
| `findOwnMatch` (matches.ts) | request → match or 404 | Loads a match by ID **and** owner; answers 404 (not 403) for other users' matches so their IDs cannot be probed. |
| `isVideoFile` (storage.ts) | file → boolean | Checks the first 12 bytes for the signatures of MP4/MOV (`ftyp`), Matroska/WebM and AVI. |
| `absolutePath` (storage.ts) | relative path → absolute path | Refuses any path that would leave the storage folder. |
| `enqueueAnalysis` (queue.ts) | `{matchId, videoPath, mode}` | Removes a finished job with the same ID (BullMQ ignores duplicate IDs), then adds the job with the match ID as job ID. |
| `countWorkers` (queue.ts) | → number | Counts distinct worker connections in Redis's client list; recognises both the Node.js and the Python BullMQ naming schemes. |
| `startQueueEventListener` | callback → listener | Converts `active`, `progress`, `completed` and `failed` events into database updates and calls the callback with the updated match. |
| `generateCoachingReport` (report.ts) | match → Markdown | Builds the statistics, calls the LLM, maps errors to `ReportError` with an HTTP status. |

### Upload handling

Uploads are processed by Multer, which streams the file to disk while it arrives, so even a 500 MB video never has to fit in memory. The file is stored under a random UUID name (the user's file name is never used as a path), and only files with a video extension and a `video/*` MIME type are accepted. Because both the extension and the MIME type are supplied by the client and can be faked, the API additionally inspects the file's first bytes (*magic numbers*) after the upload and deletes the file if it is not a real video container. Then the match row is created and the job is queued. If the queue is unreachable, the match is kept but marked FAILED with "Could not queue the analysis job", so the user can retry later with Re-analyse instead of uploading again.

### Turning queue events into live updates

The queue events of one job can arrive in bursts, for example several progress events within milliseconds. If each event started its own database update, a slower update could finish after a newer one and make the progress bar jump backwards. The listener therefore **chains** the updates of each match: every update waits for the previous update of the same match, while different matches proceed in parallel (Listing 3.5). The `failed` event checks whether the job still has attempts left; if so, the match returns to QUEUED with "Retrying after an error" instead of FAILED.

Listing: Per-match ordering of database updates (from backend/src/queue.ts)
```
const chains = new Map<string, Promise<void>>();
const update = (matchId: string, data: MatchUpdate) => {
  const next = (chains.get(matchId) ?? Promise.resolve()).then(async () => {
    // Updates for matches deleted in the meantime are simply dropped.
    const match = await prisma.match.update({ where: { id: matchId }, data }).catch(() => null);
    if (match) onUpdate(match);   // push to the user's browser
  });
  chains.set(matchId, next);
  void next.finally(() => { if (chains.get(matchId) === next) chains.delete(matchId); });
  return next;
};
```

### Error handling

Express 5 forwards errors thrown in asynchronous route handlers to the error middleware, so route code can simply throw. The central error handler in `app.ts` maps validation errors (Zod) to 400 with a readable description of the invalid fields, upload errors (Multer) to 413 for oversized files and 400 otherwise, and everything else to 500 "Internal server error", logging the details on the server without exposing them to the client. Expected business errors (not found, wrong state) are answered directly in the routes with 404 or 409.

### The coaching report

`report.ts` prepares a compact, model-friendly summary of the match: the stored summary, each team's kit colour, defended goal and formation timeline, the team shape (area, width, depth) averaged over each third of the clip, the three players who ran furthest, and the list of formation changes. This JSON is sent with a system prompt that defines the report's sections and its rules: base every statement on the numbers, never invent passes, shots or goals (they are not measured), refer to players by tracker ID, and state that conclusions from a short broadcast clip are tentative.

The request goes to a `gpt-5-mini` deployment on Azure OpenAI through the official `openai` SDK's `AzureOpenAI` client, with a 120-second timeout and two automatic retries. The output limit is set generously (8,000 tokens) because reasoning models also spend tokens on hidden reasoning before writing. SDK errors are translated into user-facing messages: invalid key and unknown deployment (502), rate limit (429), network errors (502), and the content filter. Azure OpenAI was chosen because its usage is covered by the Azure for Students credit; the design keeps the provider-specific code in this one module.

## The AI worker

### Modules

Table: Modules of the worker {widths=24,76}
| Module | Responsibility |
|---|---|
| `worker.py` | Queue consumer: takes jobs, runs the analysis in a thread, forwards progress, chooses between remote and local analysis, logs failures. |
| `src/config.py` | All parameters and thresholds in one place; loads `.env`. |
| `src/pipeline.py` | `run_analysis()`: orchestrates the stages, reports progress, builds the results file and the summary, writes them safely. |
| `src/video.py` | Video metadata and batched, strided frame reading. |
| `src/transcode.py` | `make_web_video()`: H.264 playback copy with a constant frame rate. |
| `src/detector.py` | `FootballDetector`: YOLOv8 inference and class mapping. |
| `src/tracker.py` | `FootballTracker`, `iter_tracks`, `frame_tracks_to_dataframe`: ByteTrack and the tracks table. |
| `src/homography.py` | `PitchDimensions`, `PitchKeypointDetector`, `Homography`, `HomographyEstimator`, `project_tracks`. |
| `src/clustering.py` | Roles, shirt colours, team assignment, formation templates and detection. |
| `src/trajectories.py` | Smoothing and ball gap interpolation. |
| `src/metrics.py` | Team shape, player statistics, heatmaps. |
| `src/remote.py` | Client of the remote GPU service. |
| `gpu_server.py` | The remote GPU service (FastAPI). |

The stage modules are independent of the queue and the web platform: they take and return DataFrames and can be used from scripts or tests. The classes and their relationships are shown in Figure 3.12.

![Main classes of the worker](figures/classes_worker.png){w=15.5}

### Job processing

`worker.py` creates a BullMQ `Worker` with a concurrency of one: the neural networks already use every CPU core, so analysing two videos at once would only make both slower. The worker registers under a unique name containing host name and process ID, which allows the API's health check to count workers, and uses a job lock of 120 seconds. If a worker crashes, its lock expires and BullMQ hands the job to a worker again.

The analysis is slow, synchronous code. Running it directly in the asynchronous event loop would block the loop, the job lock would not be renewed, and BullMQ would wrongly consider the job stalled. The worker therefore runs the analysis in a separate thread (`asyncio.to_thread`); progress callbacks from that thread are handed back to the event loop with `run_coroutine_threadsafe`. Failures are logged with their stack trace, and if a retry follows, the progress stage is set to "Error, retrying: ..." so the dashboard does not show a stale step.

Progress reporting is throttled by the `_Progress` helper, which only forwards an update when the integer percentage or the stage text changes. Each stage maps its own progress onto its share of the bar (Table 2.8), so the bar moves smoothly from 0 to 100 %.

The results file is written **atomically**: it is first written to a temporary file, which then replaces the target in one rename operation, so the API can never serve a half-written file. Before writing, a safety net replaces any remaining non-finite number (NaN or infinity, which JSON cannot represent) with `null` and logs how many were found, so one bad value can no longer fail an entire analysis.

### Remote GPU service

The optional GPU service (`gpu_server.py`) is a small FastAPI application that runs the same pipeline on a machine with an NVIDIA GPU. It loads the models once at start-up and offers `GET /health`, `POST /jobs` (upload a video and mode), `GET /jobs/{id}` (status and progress), `GET /jobs/{id}/results` and `/playback` (download the outputs) and `DELETE /jobs/{id}`. Every request must carry the shared secret as a Bearer token; the service refuses to start with a token shorter than 16 characters.

The design keeps the queue worker on the main server and moves only the computation (Figure 3.13). The GPU service never touches the database, the queue or the storage, so it needs no access to the platform's network, and the main server never has to be exposed to the internet. In `remote.py`, the client distinguishes two kinds of failure: `RemoteUnavailable` (the service could not be reached before any work started), after which the worker safely analyses the video locally, and `RemoteAnalysisError` (the service failed during the job), which fails the attempt and leads to the normal retry.

![Interaction between the worker and the remote GPU service](figures/gpu_sequence.png){w=13}

## The frontend

### Structure

The dashboard (`frontend/src/`) is a single-page application built with React 19 and TypeScript and bundled by Vite. Its components form the tree in Figure 3.14.

![Component structure of the dashboard](figures/frontend_components.png){w=14}

Table: Main components and modules of the dashboard {widths=24,76}
| Component / module | Responsibility |
|---|---|
| `main.tsx`, `App.tsx` | Mount the application with the router and authentication provider; define the routes. |
| `auth.tsx` | `AuthProvider` and `useAuth()`: the logged-in user, shared through React context; checks the session with `/auth/me` on start. |
| `api.ts` | Every REST call; `ApiError` with message and status; `uploadMatch()` with upload progress (XMLHttpRequest). |
| `useMatchUpdates.ts` | Hook that opens the Socket.IO connection and calls a callback for every `match:updated` event. |
| `Layout` | Header and navigation for logged-in pages; redirects visitors to the login page. |
| `AuthPage` | Login and registration form (one component, two modes). |
| `MatchesPage`, `MatchCard` | Match list with live progress, delete confirmation. |
| `UploadPage` | File selection by click or drag and drop, title, mode, upload progress. |
| `MatchPage` | Loads the match and its results; progress, error, analysis, summary and report views; re-analyse. |
| `VideoAnalysis` | Video, overlay canvas, controls, layer toggles, tactical board, formations, `PlayerPanel`. |
| `CoachingReport` | Loads, generates and renders the Markdown report. |
| `analysis/timeline.ts` | `Timeline`: the state of every person at any time, by interpolation. |
| `analysis/draw.ts` | Drawing of the video overlay and the board; hit-testing of clicks. |
| `analysis/geometry.ts` | Homography application and blending, convex hull, fitting. |
| `components/ui.tsx` | Shared UI elements: button, card, status badge, progress bar, error box, spinner, statistic. |

### Routing and navigation

Table 3.16 and Figure 3.15 show the pages and how the user moves between them. The protected pages are nested inside `Layout`, which waits until the session check has finished and redirects to `/login` when no user is logged in. Unknown URLs redirect to the match list.

Table: Routes of the dashboard {widths=24,22,54}
| Path | Page | Access |
|---|---|---|
| `/login` | `AuthPage` (login) | Public; logged-in users are redirected to `/`. |
| `/register` | `AuthPage` (register) | Public; logged-in users are redirected to `/`. |
| `/` | `MatchesPage` | Logged-in users. |
| `/upload` | `UploadPage` | Logged-in users. |
| `/matches/:id` | `MatchPage` | Logged-in owner of the match. |

![Navigation between the pages](figures/navigation.png){w=15.5}

### State management and live updates

The dashboard uses React's built-in state (`useState`, `useEffect`) and one context for the authenticated user; no global state library was needed. The session cookie is HTTP-only, so the frontend cannot read it; it learns whether the user is logged in by calling `/auth/me` at start-up. Pages subscribe to live updates with `useMatchUpdates(callback)`. The hook keeps the latest callback in a ref, so the WebSocket is opened once per page and not reconnected on every re-render. The match list replaces the updated match in its array or adds it if it is new; the match page replaces its match. When a match becomes COMPLETED, the match page downloads the results; results are stored together with the completion time they belong to, so after a re-analysis stale results are never combined with new match data.

### Synchronising overlays with the video

Drawing overlays that stay attached to the players in every frame was the main challenge of the frontend. Four techniques work together:

1. **Frame-exact timing.** The overlay is redrawn for every displayed video frame with `requestVideoFrameCallback` [25], which reports the exact media time of the frame on screen. Timers or the `timeupdate` event would lag behind by up to a quarter of a second. Browsers without this API fall back to `requestAnimationFrame` and `currentTime`.
2. **Interpolation.** The worker analyses only every 2nd or 5th frame, but the video shows every frame. `Timeline.stateAt(t)` finds the analysed frames before and after *t* by binary search and linearly interpolates boxes and pitch positions between them, so markers glide instead of jumping. It never interpolates across a gap longer than three strides (for example a camera cut).
3. **Re-projection with the camera geometry.** Paths and heatmaps are defined on the pitch, but the camera moves. For every frame, the results contain the pitch-to-image homography; `applyHomography` projects pitch points into the current frame (Listing 3.6), and between analysed frames the two matrices are blended. Points behind the camera (*w* ≤ 0) are skipped. As a result, a heatmap appears painted onto the grass and stays there while the camera pans.
4. **Drawing outside React.** The canvases are redrawn directly in the frame callback. React state holds only slowly changing things (layer toggles, selection, the displayed time), and the drawing code reads the current toggles through refs. Re-rendering the React component tree 25–50 times per second would be far too slow.

Listing: Projecting a pitch point into the current video frame (from frontend/src/analysis/geometry.ts)
```
export function applyHomography(h: number[], x: number, y: number): Point | null {
  const w = h[6] * x + h[7] * y + h[8];
  if (w <= 1e-9) return null;          // behind the camera
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}
```

The canvases are sized to their on-screen size multiplied by the device pixel ratio, so drawings are sharp on high-resolution screens; a `ResizeObserver` redraws them when the layout changes.

### Important event handlers

Table: Important event handlers of the dashboard {widths=30,70}
| Handler | Action |
|---|---|
| `AuthPage.handleSubmit` | Prevents the default form submission, calls `login` or `register`, navigates to `/` or shows the error. |
| `UploadPage.chooseFile`, `handleDrop` | Accept a file from the file dialog or drag and drop; suggest a title from the file name. |
| `UploadPage.handleSubmit` | Uploads with progress (`uploadMatch`), then opens the new match's page. |
| `MatchCard.handleDelete` | After confirmation, deletes the match and removes the card. |
| `MatchPage.reanalyse` | Queues the analysis again and shows the returned match. |
| `useMatchUpdates` callback | Applies a pushed match update to the page's state. |
| `VideoAnalysis.onOverlayClick` | Hit-tests the click against the persons' boxes in the current frame; selects/deselects a person or toggles playback. |
| `VideoAnalysis.onBoardClick` | Hit-tests the click on the tactical board. |
| `VideoAnalysis.stepFrame` | Pauses and seeks exactly one frame (aiming slightly inside the frame to avoid rounding onto its neighbour). |
| `CoachingReport.generate` | Requests a new report and displays it or the error. |

### User interface design

The dashboard uses a dark "analysis room" theme with an emerald accent colour, which keeps the attention on the video and lets the coloured overlays stand out. Layouts use responsive grids: the analysis page shows video and board side by side on wide screens and stacked on narrow ones. Interactive elements have accessible labels (`aria-label`, `aria-pressed` on the layer toggles), destructive actions require confirmation, and every asynchronous action shows a loading state and disables its button to prevent double submission.

## Security

Table: Security measures {widths=26,74}
| Threat | Measure |
|---|---|
| Stolen password database | Passwords are hashed with bcrypt, cost factor 12, with a per-password salt [19]. |
| Session theft by injected scripts (XSS) | The session token is stored in an HTTP-only cookie, which page scripts cannot read. React escapes all rendered text; the Markdown report is rendered without raw HTML. |
| Cross-site request forgery | The cookie uses `SameSite=Lax`; CORS only allows the dashboard's own origin. |
| Session interception | `Secure` cookies (HTTPS only) by default in production; configurable for local demonstrations over HTTP. |
| Account enumeration | Login answers the same message for unknown e-mail and wrong password; other users' matches answer 404, not 403. |
| Accessing other users' data | Every match query filters by the owner's ID; WebSocket updates are sent only to the owner's private room, and the socket handshake is authenticated with the same cookie. |
| Malicious uploads | Extension, MIME type and file signature are checked; files get random names; size is limited; uploads are streamed to disk. |
| Path traversal | All stored paths are resolved and checked to stay inside the storage folder, in the API and in the worker. |
| Invalid input | All request bodies and the configuration are validated with Zod schemas. |
| Leaked secrets | Secrets live only in `.env`, which is git-ignored; the GPU service requires a token of at least 16 characters; only statistics are sent to the LLM. |

## Implementation decisions and code quality

This section summarises the implementation choices not covered above.

- **Typed code everywhere.** The API is type-checked in TypeScript's strict mode, and the frontend additionally rejects unused variables and parameters and fall-through `switch` cases; the worker uses Python type hints and dataclasses (for example `Homography`, `TeamAssignment`, `FrameTracks`). The database client is generated from the schema, so database access is typed as well, and the shape of the results file is described once in `analysis/types.ts`.
- **Validation at the boundaries.** Data entering the system (requests, configuration, uploaded files, queue results) is validated where it enters; inside, the code relies on the types.
- **Vectorised data processing.** The worker processes tracking data with pandas and NumPy operations on whole columns instead of Python loops, for example the projection of all foot points in Listing 3.3, the per-track speed computation with grouped differences, and the nearest-homography join with `merge_asof`.
- **Streaming instead of loading.** Videos are read as generators of frame batches, uploads are streamed to disk, and video playback uses HTTP Range requests, so memory use does not grow with the length of the video.
- **Configuration in one place.** Every threshold of the pipeline is a named constant in `config.py` with a comment explaining its value, so experiments change one line.
- **Self-documenting code.** Identifiers are descriptive (`findOwnMatch`, `GOALKEEPER_MIN_SHARE`, `interpolate_ball`) and comments explain *why* rather than *what*, for example why the ball is not given to ByteTrack or why the homography is normalised by its norm.
- **Code reuse.** Generic helpers are shared: `ProgressBar`, `Card` and `Button` in the UI, `drawBoard` both for the main board and the player panel, one `heatmap()` function for teams, players and the ball, and the same `run_analysis()` for local and remote analysis.
- **Fault tolerance.** Retries with back-off, atomic writes, the non-finite-number safety net, fallback from GPU to local analysis, and dropping events of deleted matches make the pipeline robust against partial failures.
