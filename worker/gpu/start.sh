#!/usr/bin/env bash
# Start the GPU analysis service on port 8000.
#
#     GPU_SERVER_TOKEN=<the same secret as in your laptop's .env> bash gpu/start.sh
#
# On RunPod, port 8000 must be listed under "Expose HTTP Ports"; the service is
# then reachable at https://<POD_ID>-8000.proxy.runpod.net
set -euo pipefail
cd "$(dirname "$0")/.."   # the worker/ folder

if [ -z "${GPU_SERVER_TOKEN:-}" ]; then
  echo "Set GPU_SERVER_TOKEN first, e.g.:  GPU_SERVER_TOKEN=... bash gpu/start.sh" >&2
  exit 1
fi

export DEVICE="${DEVICE:-cuda:0}"
export PORT="${PORT:-8000}"
echo "Starting GPU analysis service on port $PORT (device $DEVICE). Stop it with Ctrl+C."
exec python gpu_server.py
