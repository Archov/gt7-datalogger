# Stage 1: build the frontend
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# Stage 2: runtime
FROM python:3.12-slim
WORKDIR /app

COPY backend/ backend/
RUN pip install --no-cache-dir ./backend

COPY --from=frontend /build/dist frontend/dist

ENV GT7_DB_PATH=/data/gt7.db \
    GT7_CARS_CSV=/app/backend/data/cars.csv \
    PYTHONUNBUFFERED=1

VOLUME /data
EXPOSE 8000
EXPOSE 33740/udp

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
