# ---------------------------------------------------------------------------
#  TimesFM 2.5 200M — Standalone Inference Service
#  PyTorch CPU | Model weights baked into image at build time
# ---------------------------------------------------------------------------

FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# HuggingFace cache directory inside the image (baked at build, used at runtime)
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV HF_HUB_OFFLINE=0

WORKDIR /app

# ---------------------------------------------------------------------------
#  1. System deps (build tools + libgomp for torch CPU)
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
#  2. Install Python dependencies
# ---------------------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
#  3. Bake model weights into the image (build-time download)
# ---------------------------------------------------------------------------
# Pass your HuggingFace token at build time:
#   docker build --build-arg HF_TOKEN=hf_xxxx ...
ARG HF_TOKEN
ENV HF_TOKEN=${HF_TOKEN}
RUN if [ -z "$HF_TOKEN" ]; then echo "WARNING: HF_TOKEN not set — gated model may fail"; fi

# Download the model files explicitly so they are cached inside the image.
# This avoids a 300 MB+ download on every container cold-start.
RUN python -c "
import os
from huggingface_hub import snapshot_download
from huggingface_hub.utils import RepositoryNotFoundError, GatedRepoError

token = os.environ.get('HF_TOKEN')
try:
    snapshot_download(
        repo_id='google/timesfm-2.5-200m-pytorch',
        cache_dir='/app/.cache/huggingface',
        token=token,
        local_files_only=False,
    )
    print('SUCCESS: model files baked into image')
except GatedRepoError as e:
    print('ERROR: Gated repository. Accept terms at https://huggingface.co/google/timesfm-2.5-200m-pytorch and provide HF_TOKEN.')
    raise
except RepositoryNotFoundError as e:
    print('ERROR: Repository not found or no access.')
    raise
"

# After baking, we can optionally switch to offline mode for safety
ENV HF_HUB_OFFLINE=1

# ---------------------------------------------------------------------------
#  4. Copy application code
# ---------------------------------------------------------------------------
COPY main.py .
COPY mcp_server.py .

# ---------------------------------------------------------------------------
#  5. Runtime settings
# ---------------------------------------------------------------------------
EXPOSE 8000
EXPOSE 8001

# Health-check for ACA (FastAPI port)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default command: run the REST server.
# For MCP mode override with:  python mcp_server.py
ENV PORT=8000
ENV MCP_PORT=8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
