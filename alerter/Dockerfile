FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
WORKDIR /app
COPY alerter/*.py alerter/rules.json /app/
COPY dashboard/backend/filterlog.py /app/filterlog.py
RUN python -m unittest discover -s /app -p 'test_*.py' -v
USER 1000:1000
CMD ["python", "checker.py"]
