# ilmhubstt — CPU server uchun obraz (GPU uchun: nvidia/cuda asosidagi obraz kerak, docs/DEPLOY.md)
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend/dist frontend/dist
ENV HOST=0.0.0.0 PORT=8000 DATA_DIR=/data MODEL_DIR=/models
VOLUME ["/data", "/models"]
EXPOSE 8000
WORKDIR /app/backend
CMD ["python", "run.py"]
