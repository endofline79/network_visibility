FROM node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9 AS frontend
WORKDIR /build
COPY dashboard/frontend/package*.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY dashboard/frontend/ ./
RUN npm run test:routes && npm run build

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS backend-test
WORKDIR /app
COPY dashboard/requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt
COPY dashboard/backend/ backend/
COPY dashboard/tests/ tests/
RUN python -m unittest discover -s tests -v

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY dashboard/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=backend-test /app/backend/ backend/
COPY --from=frontend /build/dist/ static/
USER 1000:1000
EXPOSE 8095
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8095/api/health',timeout=3)"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8095", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "32"]
