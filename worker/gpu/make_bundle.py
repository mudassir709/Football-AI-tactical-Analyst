"""Pack the worker code into a zip for uploading to a cloud GPU machine.

Run on your own computer, from the repository root:
    python worker/gpu/make_bundle.py

Creates tactical-eye-gpu.zip in the repository root (ignored by Git). Videos,
model weights and outputs are left out: the GPU machine downloads the models
itself (gpu/setup.sh) and receives videos from the worker.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = WORKER_DIR.parent
OUTPUT = REPO_ROOT / "tactical-eye-gpu.zip"

INCLUDE = ["gpu_server.py", "src", "gpu"]
SKIP_PARTS = {"__pycache__"}


def main() -> None:
    files = []
    for name in INCLUDE:
        path = WORKER_DIR / name
        files.extend(p for p in ([path] if path.is_file() else path.rglob("*")) if p.is_file())
    files = [p for p in files if not SKIP_PARTS & set(p.parts) and p.suffix != ".zip"]

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            # Keep a top-level "worker/" folder inside the zip.
            bundle.write(path, Path("worker") / path.relative_to(WORKER_DIR))
        # Empty folders the service expects.
        for folder in ("models", "data", "outputs"):
            bundle.writestr(f"worker/{folder}/.gitkeep", "")

    print(f"Created {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB, {len(files)} files)")


if __name__ == "__main__":
    main()
