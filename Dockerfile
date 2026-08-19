# Stage 1: build the frontend.
# Pinned to the *builder's* platform: the only output is static JS/CSS/HTML, so
# on a multi-arch build this runs once natively instead of again under emulation.
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# Stage 2: runtime
FROM python:3.12-slim
WORKDIR /app

# Links the image to the repo on GHCR. CI overrides this via docker/metadata-action;
# it is set here so locally built images carry it too.
LABEL org.opencontainers.image.source="https://github.com/jbhoorasingh/gt7-datalogger"

COPY backend/ backend/
RUN pip install --no-cache-dir ./backend

COPY --from=frontend /build/dist frontend/dist

ENV GT7_DB_PATH=/data/gt7.db \
    GT7_METRICS_DB_PATH=/metrics/gt7-metrics.db \
    GT7_CARS_CSV=/app/backend/data/cars.csv \
    PYTHONUNBUFFERED=1

VOLUME /data /metrics
EXPOSE 8000
EXPOSE 33740/udp

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
