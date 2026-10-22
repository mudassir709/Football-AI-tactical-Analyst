# Football AI Tactical Analyst

A web platform that turns football match footage into interactive tactical data.
Users upload a match clip; a background AI worker detects and tracks every
player and the ball, maps them onto a 2D pitch, assigns teams, detects
formations and computes tactical metrics. The dashboard then draws movement
paths, heatmaps and a synchronised 2D tactical board directly over the video.

## Architecture

```
React dashboard  <--REST / WebSocket-->  Node.js API  --job-->  Redis queue  --job-->  Python AI worker
 (upload, video overlays,                (auth, uploads,                                (detection, tracking,
  2D board, heatmaps)                     job status)                                    homography, teams,
                                              |                                          formations, metrics)
                                              +----------------- PostgreSQL <------------------+
```

Heavy video processing never runs inside a web request: the API puts a job on
a queue and returns immediately, a worker processes it in the background and
reports progress, and the browser is notified over a WebSocket when results are
ready. All services run in Docker containers; GitHub Actions tests and builds
them on every push.

## Repository layout

| Folder | Contents | Status |
|---|---|---|
| `worker/` | Python AI pipeline (YOLOv8, ByteTrack, homography, clustering) | Pipeline complete; queue consumer next |
| `backend/` | Node.js + Express API, authentication, job management | Planned |
| `frontend/` | React + TypeScript dashboard | Planned |
| `docs/` | Architecture, requirements and thesis documentation | In progress |

### AI worker modules (`worker/src/`)

| Module | Responsibility |
|---|---|
| `config.py` | All paths, thresholds and model settings in one place |
| `video.py` | Reads video frames in strided batches |
| `detector.py` | YOLOv8 detection of players, goalkeepers, referees and the ball |
| `tracker.py` | ByteTrack tracking with stable player IDs; tracks saved to parquet |
| `homography.py` | Pitch keypoints -> per-frame homography -> pitch coordinates in metres |
| `clustering.py` | Team assignment by jersey colour; formation detection |
| `trajectories.py` | Position smoothing and ball gap interpolation |

## Running the AI pipeline (worker)

Requires Python 3.12+ and the two Roboflow model files in `worker/models/`
(`football-player-detection.pt`, `football-pitch-detection.pt`) and a clip at
`worker/data/sample.mp4`.

```bash
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r worker/requirements.txt

cd worker
python scripts/test_tracking.py      # detection + tracking  -> outputs/*_tracks.parquet
python scripts/test_homography.py    # pitch coordinates     -> outputs/*_tracks_pitch.parquet
python scripts/test_teams.py         # team assignment       -> outputs/*_tracks_teams.parquet
python scripts/test_formation.py     # formations            -> outputs/*_formations.parquet
```

Each script writes preview videos or plots to `worker/outputs/` for visual checks.

## Performance note

On the development laptop (Intel i7-1255U, CPU inference) detection runs at
about 3 s per frame. This is why processing is asynchronous: results are
computed once by the worker and stored, so the dashboard loads them instantly.
