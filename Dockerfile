# autogram — CPU-only container. Bundles Ollama so the LLM runtime works
# out of the box. Models are pulled at first run into the mounted volumes.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/huggingface \
    OLLAMA_MODELS=/data/ollama/models \
    OLLAMA_HOST=http://127.0.0.1:11434

# System deps: curl for the Ollama installer, libgomp for torch, ca-certs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama (Linux). The daemon lifecycle is still managed by autogram.
RUN curl -fsSL https://ollama.com/install.sh | sh

WORKDIR /app

# Install python deps first for layer caching.
COPY requirements.txt requirements-cpu.txt ./
RUN pip install --upgrade pip && pip install -r requirements-cpu.txt

COPY . .
RUN pip install -e .

# Persist model caches and state across runs.
VOLUME ["/data", "/app/state", "/app/out"]

ENTRYPOINT ["python", "-m", "autogram.run"]
CMD ["--dry-run"]
