FROM netsampler/goflow2:v2.2.6@sha256:b930e69d1bc7bd765da5b45d12f04edd10970c310b33ba44fd12a07a870da8e6 AS decoder
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=decoder /goflow2 /usr/local/bin/goflow2
COPY collector/ /app/
RUN python -m unittest -v test_collector test_decoder
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=3)"]
CMD ["python", "collector.py"]
