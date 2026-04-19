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
# toolchain at runtime.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
       tesseract-ocr \
       ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.6

COPY pyproject.toml README.md ./
COPY src ./src

# Install the package itself. Add `[observability]` here if/when we
# wire OTel in prod — opt-in keeps the local image lean.
RUN uv pip install --system .

# Cloud Run injects PORT (default 8080); local uses the ENV default
# above. Bind to all interfaces so the container is reachable from
# the proxy.
CMD ["sh", "-c", "uvicorn caseops_api.main:app --host 0.0.0.0 --port ${PORT} --app-dir src"]
