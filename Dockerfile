FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 wattproof

WORKDIR /app

COPY requirements.txt requirements-prod.txt ./
RUN python -m pip install --no-cache-dir -r requirements-prod.txt

COPY --chown=wattproof:wattproof run.py ./
COPY --chown=wattproof:wattproof wattproof ./wattproof
COPY --chown=wattproof:wattproof fixtures ./fixtures
COPY --chown=wattproof:wattproof sources ./sources
COPY --chown=wattproof:wattproof assets/pge-anonymous-3ce-sample-bill.pdf ./assets/pge-anonymous-3ce-sample-bill.pdf

USER wattproof
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "run:app"]

