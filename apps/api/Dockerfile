FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.6

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv pip install --system .

CMD ["uvicorn", "caseops_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
