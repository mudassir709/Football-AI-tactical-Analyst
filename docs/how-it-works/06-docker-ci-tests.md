# How it works: containers, CI/CD, tests and the coaching report

## Containers (Docker)

Every service has a `Dockerfile` that describes how to build its image:

| Image | Base | Contents |
|---|---|---|
| `backend` | `node:24-alpine` | API code; applies database migrations on start-up |
| `frontend` | `node:24-alpine` (build) → `nginx:1.27-alpine` (serve) | Production React build; nginx also proxies `/api` and WebSockets to the backend |
| `worker` | `python:3.12-slim` | Pipeline + queue worker with **CPU-only** PyTorch (~3.4 GB; the GPU build would add several GB of CUDA libraries); heavy analysis can still be offloaded to the cloud GPU service |

Model weights (270 MB) are **mounted**, not baked into the image, so images
stay small and the CI pipeline needs no model files.

```bash
# Development: only PostgreSQL + Redis in Docker, everything else run directly
docker compose up -d

# Whole platform in containers -> http://localhost:8080
docker compose --profile app up -d --build
```

The `app` profile keeps the two modes separate: development keeps fast
hot-reloading, while the containerised mode is what a server would run.

## Continuous integration and delivery (GitHub Actions)

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | What it checks |
|---|---|
| Backend | Dependencies install, Prisma client generates, TypeScript type check |
| Frontend | Lint (oxlint), TypeScript check, production build |
| Worker | 30 unit tests (pytest) |
| Docker images | All three images build; on pushes to `main` they are **published** to GitHub Container Registry (`ghcr.io/<owner>/tactical-eye-<service>`) |

The image job only runs when all checks pass, so a published image is always
a tested one. Build layers are cached between runs to keep pipelines fast.

## Automated tests (`worker/tests/`)

Run with `cd worker && python -m pytest`. They need no videos or models.

| File | Covers |
|---|---|
| `test_homography.py` | Fitting a homography from pitch landmarks, rejecting a wrong landmark (RANSAC), rejecting collinear landmarks, projecting feet to the pitch, and a regression test for the NaN-matrix bug |
| `test_clustering.py` | Measuring shirt colour against the local grass (including a lime-green kit, regression test for the green-kit bug) and recognising all 9 formations from noisy positions |
| `test_export.py` | NaN/inf safety net in the results file, ball-gap interpolation, position smoothing |

Each bug found during development got a regression test, so it cannot
silently come back.

## AI coaching report (Azure OpenAI)

On a completed match, **Generate report** sends the computed statistics
(formations over time, compactness, width/depth per third of the clip,
top runners) to a GPT model deployed on Azure OpenAI and shows the returned
Markdown report. Azure was chosen because it is covered by the Azure for
Students credit from the GitHub Student Developer Pack.

- Only numbers are sent, never video. The prompt forbids inventing events
  (passes, shots, goals) that the analysis does not measure, and asks the
  model to state the limits of a short broadcast clip.
- The report is stored with the match and can be regenerated, so a demo
  can show saved reports without new API calls.
- Errors (invalid key, wrong deployment name, rate limit, network, content
  filter) are shown as clear messages.
- Configured with `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` and
  `AZURE_OPENAI_DEPLOYMENT`; disabled automatically when they are not set.

Code: `backend/src/report.ts`, `frontend/src/components/CoachingReport.tsx`.
