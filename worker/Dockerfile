# AI worker image (Python): queue consumer that runs the analysis pipeline.
#
# Uses the CPU build of PyTorch (no CUDA libraries) to keep the image smaller;
# heavy analysis can be offloaded to the cloud GPU service via GPU_SERVER_URL.
# Model weights are not baked in: mount them at /app/models (see docker-compose).
FROM python:3.12-slim

# System libraries OpenCV needs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so this layer is cached until the requirements change.
COPY requirements-docker.txt ./
COPY gpu/requirements-gpu.txt ./gpu/
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-docker.txt

COPY src ./src
COPY worker.py gpu_server.py ./

ENV PYTHONUNBUFFERED=1 \
    DEVICE=cpu \
    STORAGE_DIR=/storage

CMD ["python", "worker.py"]
