FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY dashboard/backend/pihole.py dashboard/backend/unifi.py backend/
COPY telemetry/worker.py telemetry/test_worker.py ./
COPY dashboard/tests/test_pihole.py dashboard/tests/test_unifi.py tests/
RUN python -m unittest discover -s tests -v && python -m unittest test_worker -v
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD ["python", "-c", "import json,time; s=json.load(open('/analysis/telemetry-status.json')); assert time.time()-s['updated_at'] < 90; assert all(not v['stale'] for v in s['sources'].values()); assert not s['sources']['pihole']['archive']['error']; assert all(not v['error'] for v in s['snapshot_archives'].values())"]
CMD ["python", "worker.py"]
