FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "psycopg[binary]==3.2.3" \
    "google-cloud-compute==1.19.2"

COPY watchdog.py /watchdog.py

CMD ["python", "/watchdog.py"]
