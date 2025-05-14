
# -----------------   Pyhton image   -----------------
FROM python:3.13-slim

ARG BASE_DIR=/app/
WORKDIR ${BASE_DIR}

RUN apt-get update && \
    apt-get install -y build-essential curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ${BASE_DIR}
RUN pip3 install --no-cache-dir -r requirements.txt

COPY *.py ${BASE_DIR}
COPY templates/ ${BASE_DIR}/templates/

CMD ["python3", "app_initr_influx.py"]
