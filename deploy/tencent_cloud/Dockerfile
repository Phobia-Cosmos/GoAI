FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8080

WORKDIR /app
COPY src/ src/
COPY scripts/run_web_platform.py scripts/run_web_platform.py
COPY data/processed/v2/matches/LX_XA/rules.json data/processed/v2/matches/LX_XA/rules.json

EXPOSE 8080
CMD ["/bin/sh", "-c", "python scripts/run_web_platform.py --host 0.0.0.0 --port ${PORT} --match-dir data/processed/v2/matches/LX_XA"]
