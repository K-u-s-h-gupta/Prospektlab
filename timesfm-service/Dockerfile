# TimesFM 2.5 200M — Standalone Inference Service
# PyTorch CPU | Model weights baked into image at build time

FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# HuggingFace cache directory inside the image (baked at build, used at runtime)
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV HF_HUB_OFFLINE=0

WORKDIR /app

# 1. System deps (build tools + git + libgomp for torch CPU)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 2. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# 3. Install TimesFM from GitHub (modern v2.5, not ancient PyPI 1.0.0)
RUN pip install --no-cache-dir \
    git+https://github.com/google-research/timesfm.git

# 4. Bake model weights into the image (build-time download)
ARG HF_TOKEN
ENV HF_TOKEN=${HF_TOKEN}
COPY download_model.py .
RUN if [ -z "$HF_TOKEN" ]; then \
        echo "WARNING: HF_TOKEN not set — gated model may fail"; \
    fi && \
    python download_model.py

# After baking, switch to offline mode for safety
ENV HF_HUB_OFFLINE=1

# 5. Copy application code
COPY main.py .
COPY mcp_server.py .

# 6. Runtime settings
EXPOSE 8000
EXPOSE 8001

# Health-check for ACA (FastAPI port)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen(\"http://localhost:8000/health\")" || exit 1

ENV PORT=8000
ENV MCP_PORT=8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
