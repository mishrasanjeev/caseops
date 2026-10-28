# CaseOps API container — Python 3.13 + uv + tesseract for OCR.
# Built for Cloud Run: binds to ${PORT} (default 8000 for local).
FROM python:3.13-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
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

# Remove only the compromised root from Debian's effective default trust store.
COPY docker/remove_compromised_ca.py /tmp/caseops-remove-compromised-ca.py
RUN python /tmp/caseops-remove-compromised-ca.py \
  && rm /tmp/caseops-remove-compromised-ca.py

# Without legacy-certs pip preloads its independent, still-affected certifi store.
# Verification stays enabled against this explicitly selected patched OS bundle.
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    PIP_USE_DEPRECATED=legacy-certs
RUN pip install --no-cache-dir uv==0.13.4

FROM runtime-base AS api

COPY pyproject.toml uv.lock README.md ./
COPY vendor/fastembed-0.8.0-1caseops1-py3-none-any.whl ./vendor/
COPY vendor/fastembed-0.8.0-1caseops1.json ./vendor/
# API-only LGPL notices and the exact unmodified corresponding source archive.
# The web/mobile JavaScript notice and exception inventories are separate.
COPY vendor/fpdf2-2.8.8 /usr/share/doc/caseops-api/third-party/fpdf2-2.8.8
# The official dnspython 2.9.0 archives omit their tagged ISC notice.
COPY vendor/dnspython-2.9.0 /usr/share/doc/caseops-api/third-party/dnspython-2.9.0

# Install the package with the [ocr] extra so rapidocr + pytesseract
# ship to Cloud Run by default. Without these, the prod image silently
# skips OCR fallback when pdfminer returns sparse text — and scanned
# matter attachments + older judgment PDFs then miss chunking / embed.
# Add `[observability]` here if/when we wire OTel in prod.
# Preserve the lock's exact artifact URLs and hashes. Name-only requirements
# otherwise re-fetch large live package indexes during an immutable install.
RUN uv export \
      --offline \
      --frozen \
      --format pylock.toml \
      --no-dev \
      --extra ocr \
      --no-emit-project \
      --no-header \
      --output-file /app/pylock.toml \
  && uv pip install --system --requirements /app/pylock.toml \
  && rm /app/pylock.toml \
  && python /usr/share/doc/caseops-api/third-party/fpdf2-2.8.8/verify.py --installed \
  && python -m compileall -q --invalidation-mode checked-hash /usr/local/lib/python3.13/site-packages

# Voyage token counting uses Hugging Face's tokenizer cache before every
# embedding request. Download the production tokenizer while the image is
# built so a cold Cloud Run instance never holds an upload response open while
# it resolves that asset from the network.
RUN python -c "from tokenizers import Tokenizer; tokenizer = Tokenizer.from_pretrained('voyageai/voyage-4-large'); tokenizer.no_truncation()"

# Pre-download the fastembed cross-encoder (jina-reranker-v1-tiny-en,
# ~130 MB ONNX) at build time so Cloud Run cold starts don't eat a
# multi-second download on the first reranked query. The model caches
# under /root/.cache/fastembed and stays in the image layer.
RUN python -c "import math; from fastembed.rerank.cross_encoder import TextCrossEncoder; encoder = TextCrossEncoder(model_name='jinaai/jina-reranker-v1-tiny-en'); scores = list(encoder.rerank('regular bail triple test', ['A tax assessment determines taxable income.', 'The court grants regular bail after applying the triple test.'])); assert len(scores) == 2 and all(math.isfinite(float(score)) for score in scores) and scores[1] > scores[0]"

# Keep dependency and embedded-model layers independent of application source.
# The project install creates console entry points used by Cloud Run jobs and
# workers; runtime dependencies above remain locked and are not re-resolved.
COPY alembic.ini ./
COPY src ./src
COPY alembic ./alembic
RUN uv pip install --system --no-deps . \
  && python -m compileall -q --invalidation-mode checked-hash \
       /app/src /usr/local/lib/python3.13/site-packages/caseops_api

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
CMD ["sh", "-c", "uvicorn caseops_api.main:app --no-proxy-headers --host 0.0.0.0 --port ${PORT} --app-dir src"]
