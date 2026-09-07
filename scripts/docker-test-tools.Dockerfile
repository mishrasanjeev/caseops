ARG CASEOPS_TEST_BASE_IMAGE
FROM ${CASEOPS_TEST_BASE_IMAGE}

ARG TEMPORAL_TEST_SERVER_CACHE_PATH=/tmp/temporal-test-server-sdk-python-1.27.2
ARG TEMPORAL_TEST_SERVER_SHA256=daa58458d32f6254a901085c27ad1c19a64a4e171679ed08b5b92c298baba6ce

RUN install -D -m 755 "${TEMPORAL_TEST_SERVER_CACHE_PATH}" /opt/caseops-test-tools/temporal-test-server \
    && printf '%s  %s\n' "${TEMPORAL_TEST_SERVER_SHA256}" /opt/caseops-test-tools/temporal-test-server | sha256sum --check --strict

ENV CASEOPS_TEST_TEMPORAL_SERVER_PATH=/opt/caseops-test-tools/temporal-test-server \
    CASEOPS_TEST_TEMPORAL_SERVER_SHA256=${TEMPORAL_TEST_SERVER_SHA256}

# Offline regeneration of pinned official legal-source PDFs; not a runtime dependency.
RUN python -m venv /opt/caseops-test-tools/statute-compiler \
    && /opt/caseops-test-tools/statute-compiler/bin/pip install --no-cache-dir pdfplumber==0.11.9

# A base image's historical runner must never choose a source tree or report path.
ENTRYPOINT ["python", "-c", "raise SystemExit('Test tools require an explicit --entrypoint and a current-source runner.')"]
CMD []
