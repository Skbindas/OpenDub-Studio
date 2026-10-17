FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENDUB_HOST=0.0.0.0 \
    OPENDUB_PORT=7860 \
    OPENDUB_DATA_DIR=/data/runtime \
    OPENDUB_EMBED_WORKER=0

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .
RUN mkdir -p /data/runtime
EXPOSE 7860
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "7860"]
