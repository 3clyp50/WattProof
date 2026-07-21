FROM python:3.13-slim

ARG CODEX_VERSION=0.145.0
ARG CODEX_SHA256=bfaf13c9ba34f2ad764e4a916c49cf7177aeba329cf0f719e2227566fc8d662a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends bubblewrap poppler-utils \
    && python -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
        "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-x86_64-unknown-linux-musl.tar.gz" \
        /tmp/codex.tar.gz \
    && echo "${CODEX_SHA256}  /tmp/codex.tar.gz" | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/codex.tar.gz --directory /usr/local/bin \
    && mv /usr/local/bin/codex-x86_64-unknown-linux-musl /usr/local/bin/codex \
    && rm /tmp/codex.tar.gz \
    && codex --version \
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

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "180", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
