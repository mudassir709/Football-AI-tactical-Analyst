# How it works: analysing on a cloud GPU (RunPod)

The AI models are by far the slowest part of the analysis. On the development
laptop's CPU they take about 3.6 s per analysed frame; a cloud GPU is roughly
20-100x faster. The platform can therefore offload analysis to a **GPU
analysis service** running on a rented cloud machine.

## Design

```
Laptop:  API → Redis queue → Worker ──HTTPS: upload video──▶ Cloud GPU: gpu_server.py
                                │    ◀──────── progress ─────     (same pipeline, on the GPU)
                                │    ◀── results + playback ──
                                └── stores files, reports progress to the browser as usual
```

- The **queue worker stays on the laptop**. It still takes jobs from Redis and
  reports progress to the API; only the heavy computation moves.
- The **GPU service** (`worker/gpu_server.py`) is a small FastAPI web service:
  upload a video, poll its progress, download the results. It never touches
  the database, queue or file storage, so it needs only an HTTPS address and
  a shared secret token, and the laptop never has to be exposed to the internet.
- **Automatic fallback**: if `GPU_SERVER_URL` is empty, or the service cannot be
  reached when a job starts, the worker analyses the video locally instead.
- The dashboard shows where each match was processed ("Processing time … on
  GPU (NVIDIA …)").

This is a common production pattern: a job orchestrator delegates model
inference to a separate, independently scalable inference service.

## Step-by-step: running the GPU service on RunPod

Costs: you pay per second only while the machine (a "pod") is running.
Delete the pod when you are done.

### 1. Prepare on your laptop

```bash
python worker/gpu/make_bundle.py        # creates tactical-eye-gpu.zip in the project folder
```

Open your `.env` and copy the value of `GPU_SERVER_TOKEN` (you will paste it
on the pod in step 4). Never share this token publicly.

### 2. Create the pod

1. Log in at runpod.io, add credit under **Billing** if needed.
2. Go to **Pods → Deploy**.
3. Choose a GPU, for example **RTX 3090**, **RTX 4090** or **RTX A4000**.
4. Template: the official **RunPod PyTorch** template (includes JupyterLab).
5. Click **Edit Template** (or "Customize deployment"):
   - **Expose HTTP Ports**: make sure `8000` is listed (keep `8888` for JupyterLab).
   - **Container disk**: 20 GB is enough.
6. Choose **On-Demand** (not Spot/Interruptible, which can be stopped at any time).
7. **Deploy**, and wait until the pod shows as running.

### 3. Upload and install

1. On the pod, click **Connect → Jupyter Lab** (port 8888).
2. Drag `tactical-eye-gpu.zip` into JupyterLab's file browser (the `/workspace` folder).
3. Open **File → New → Terminal** and run:

```bash
cd /workspace
python -m zipfile -e tactical-eye-gpu.zip .
cd worker
bash gpu/setup.sh
```

Setup installs the packages, downloads both models (~280 MB) and checks the
GPU. It ends with a line like `GPU: NVIDIA GeForce RTX 3090`.

### 4. Start the service

In the same terminal (replace `PASTE_TOKEN_HERE` with the token from your `.env`):

```bash
GPU_SERVER_TOKEN=PASTE_TOKEN_HERE nohup bash gpu/start.sh > server.log 2>&1 &
tail -f server.log      # wait for "Models loaded on GPU (...)", then Ctrl+C to stop watching
```

`nohup … &` keeps the service running even if you close the JupyterLab tab.

### 5. Connect the platform

1. Copy the pod's ID from the RunPod page. The service address is
   `https://<POD_ID>-8000.proxy.runpod.net`.
2. Check it in your browser: `https://<POD_ID>-8000.proxy.runpod.net/health`
   should show `{"status":"ok","device":"GPU (NVIDIA …)", …}`.
3. In your laptop's `.env`, set `GPU_SERVER_URL=https://<POD_ID>-8000.proxy.runpod.net`.
4. **Restart the worker** (Ctrl+C in its terminal, then `python worker.py` again).

Upload a match: the progress bar now shows stages like
"Detecting and tracking players (on GPU (NVIDIA GeForce RTX 3090))".

### 6. When you are done: stop paying

1. In RunPod, **Terminate** (delete) the pod. *Stop* keeps the disk and still
   costs a little per month; *Terminate* costs nothing afterwards.
2. In `.env`, empty `GPU_SERVER_URL=` and restart the worker (not strictly
   needed, since the worker falls back automatically, but it avoids a short
   connection attempt on every job).

To use the GPU again later (e.g. on presentation day), repeat steps 2-5;
about 10-15 minutes.

## Troubleshooting

| Problem | Cause / fix |
|---|---|
| `/health` page does not load | Port 8000 not exposed (step 2.5), or the service is not running: check `server.log` on the pod |
| Worker log says "GPU service unavailable" | `GPU_SERVER_URL` wrong, or worker not restarted after editing `.env` |
| Job fails with "Invalid or missing token" | The token on the pod differs from `GPU_SERVER_TOKEN` in `.env` |
| `setup.sh` says CUDA is not available | The pod has no GPU or uses a non-PyTorch template |
| Progress says "(on CPU)" | `DEVICE` was overridden; `start.sh` uses `cuda:0` by default |

## Security

- Every request except `/health` needs the shared token, compared in
  constant time; RunPod's proxy provides HTTPS.
- Only the video travels to the GPU machine; no user accounts, passwords or
  database access. Videos and results are deleted from the GPU machine once the
  worker has downloaded them (or after two hours at most).
