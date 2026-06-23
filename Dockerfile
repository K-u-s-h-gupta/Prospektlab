FROM public.ecr.aws/docker/library/python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies (needed for Crawl4AI/Chromium, reportlab, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    # Chromium system libs required by crawl4ai-setup on debian-slim
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file from the active backend package tree
COPY backend/finagent/requirements-finagent.txt ./

# Install python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements-finagent.txt

# Install Chromium for Crawl4AI (downloads browser binary via Playwright under the hood).
# crawl4ai-setup is the console_scripts entry point installed by the crawl4ai package.
RUN crawl4ai-setup

# Copy the application code
# The runtime package lives in backend/finagent; copy it into /app/finagent.
COPY backend/finagent/ ./finagent/

# Copy helper scripts (includes upstox_token_scheduler.py for daily token refresh)
COPY scripts/ ./scripts/

# Expose the port FastAPI runs on
EXPOSE 8080

# Command to run the application
CMD ["uvicorn", "finagent.gateway.run:app", "--host", "0.0.0.0", "--port", "8080"]
