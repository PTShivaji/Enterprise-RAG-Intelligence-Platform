# syntax=docker/dockerfile:1.7
# Enterprise RAG backend: FastAPI + Sentence-Transformers (CPU) + pgvector.
# Build context: repository root (see docker-compose.yml).

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data/hf_cache

WORKDIR /app

# CPU-only PyTorch first: the default Linux wheel pulls ~2 GB of CUDA libraries.
COPY backend/requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.15.0+cpu" \
 && grep -v '^torch==' requirements.txt > /tmp/req.txt \
 && pip install -r /tmp/req.txt

# Optionally bake the models into the image (offline start-up, larger image).
ARG PRELOAD_MODELS=false
RUN if [ "$PRELOAD_MODELS" = "true" ]; then python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"; fi

COPY backend/alembic.ini backend/pyproject.toml ./
COPY backend/alembic ./alembic
COPY backend/app ./app
# The evaluation runner resolves <repo>/evaluation/datasets; in the image that is /evaluation/datasets.
COPY evaluation/datasets /evaluation/datasets

RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data/storage /data/hf_cache \
 && chown -R app:app /data
USER app

EXPOSE 8000
# Apply migrations, then serve. One worker: models are loaded per process (~400 MB RAM each).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
