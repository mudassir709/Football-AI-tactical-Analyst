#!/usr/bin/env bash
# One-time setup of the GPU analysis service on a cloud GPU machine (RunPod or
# any Linux machine with an NVIDIA GPU and PyTorch+CUDA preinstalled).
#
# Run from the unpacked worker/ folder:
#     bash gpu/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."   # the worker/ folder

echo "== 1/4 System libraries for OpenCV"
if command -v apt-get >/dev/null; then
  apt-get update -qq && apt-get install -y -qq libgl1 libglib2.0-0 >/dev/null || \
    echo "   (could not install system libraries; continuing)"
fi

echo "== 2/4 Python packages (keeps the machine's own PyTorch)"
python -m pip install -q --upgrade pip
python -m pip install -q -r gpu/requirements-gpu.txt

echo "== 3/4 Model weights (Roboflow pretrained football models)"
mkdir -p models
[ -f models/football-player-detection.pt ] || \
  gdown -q -O models/football-player-detection.pt "https://drive.google.com/uc?id=17PXFNlx-jI7VjVo_vQnB1sONjRyvoB-q"
[ -f models/football-pitch-detection.pt ] || \
  gdown -q -O models/football-pitch-detection.pt "https://drive.google.com/uc?id=1Ma5Kt86tgpdjCTKfum79YMgNnSjcoOyf"
ls -lh models/*.pt

echo "== 4/4 Checking the GPU"
python - <<'PY'
import sys, torch
if not torch.cuda.is_available():
    sys.exit("CUDA is not available - did you pick a GPU machine with a PyTorch image?")
print(f"   Python {sys.version.split()[0]}, PyTorch {torch.__version__}, GPU: {torch.cuda.get_device_name(0)}")
PY

echo
echo "Setup complete. Start the service with:  bash gpu/start.sh"
