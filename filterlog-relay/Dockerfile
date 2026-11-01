FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY presentation/backend/filterlog.py /app/filterlog.py
COPY filterlog-relay/relay.py /app/relay.py
USER 1000:1000
EXPOSE 1515
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD ["python","-c","import socket; s=socket.create_connection(('127.0.0.1',1515),3); s.close()"]
CMD ["python","-u","/app/relay.py"]
