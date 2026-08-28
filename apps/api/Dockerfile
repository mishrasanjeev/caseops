# CaseOps API container — Python 3.13 + uv + tesseract for OCR.
# Built for Cloud Run: binds to ${PORT} (default 8000 for local).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# OCR runtime + libpq runtime headers for psycopg's binary wheel fall-
# back path. Build deps stay in the layer below; we never need a C
# toolchain at runtime. Tesseract language packs cover the Indian
# courts we target (English + Hindi + Marathi + Tamil + Telugu +
# Kannada); regional languages matter because some HC scans carry
# judgment text in the vernacular.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
       tesseract-ocr \
       tesseract-ocr-hin \
       tesseract-ocr-mar \
       tesseract-ocr-tam \
       tesseract-ocr-tel \
       tesseract-ocr-kan \
       ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.6

COPY pyproject.toml uv.lock README.md ./

# Install the package with the [ocr] extra so rapidocr + pytesseract
# ship to Cloud Run by default. Without these, the prod image silently
# skips OCR fallback when pdfminer returns sparse text — and scanned
# matter attachments + older judgment PDFs then miss chunking / embed.
# Add `[observability]` here if/when we wire OTel in prod.
RUN uv export \
      --frozen \
      --no-dev \
      --extra ocr \
      --no-emit-project \
      --no-header \
      --no-hashes \
      --output-file /tmp/requirements.lock \
  && uv pip install --system --requirements /tmp/requirements.lock \
  && rm /tmp/requirements.lock

# Voyage token counting uses Hugging Face's tokenizer cache before every
# embedding request. Download the production tokenizer while the image is
# built so a cold Cloud Run instance never holds an upload response open while
# it resolves that asset from the network.
RUN python -c "from tokenizers import Tokenizer; tokenizer = Tokenizer.from_pretrained('voyageai/voyage-4-large'); tokenizer.no_truncation()"

# Pre-download the fastembed cross-encoder (jina-reranker-v1-tiny-en,
# ~130 MB ONNX) at build time so Cloud Run cold starts don't eat a
# multi-second download on the first reranked query. The model caches
# under /root/.cache/fastembed and stays in the image layer.
RUN python -c "from fastembed.rerank.cross_encoder import TextCrossEncoder; TextCrossEncoder(model_name='jinaai/jina-reranker-v1-tiny-en')"

# Keep dependency and embedded-model layers independent of application source.
# The project install creates console entry points used by Cloud Run jobs and
# workers; runtime dependencies above remain locked and are not re-resolved.
COPY alembic.ini ./
COPY src ./src
COPY alembic ./alembic
RUN uv pip install --system --no-deps .

# Both model families are now baked into immutable image layers. Force runtime
# resolution through those caches so cold workers never probe the public Hub.
# Use the native Tesseract installation above for OCR; RapidOCR resolves its
# ONNX models lazily and must not make an interactive request wait on a model
# download.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    CASEOPS_OCR_PROVIDER=tesseract

ARG CASEOPS_RELEASE_SHA=unavailable
LABEL org.opencontainers.image.revision=$CASEOPS_RELEASE_SHA

# Cloud Run injects PORT (default 8080); local uses the ENV default
# above. Bind to all interfaces so the container is reachable from
# the proxy.
CMD ["sh", "-c", "uvicorn caseops_api.main:app --host 0.0.0.0 --port ${PORT} --app-dir src"]
