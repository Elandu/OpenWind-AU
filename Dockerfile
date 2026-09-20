FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN python -m pip install --no-cache-dir --upgrade pip build

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY data ./data

RUN python -m build --wheel --outdir /dist


FROM python:3.12-slim AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENWIND_HOST=0.0.0.0 \
    OPENWIND_PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system openwind \
    && useradd --system --gid openwind --home-dir /var/lib/openwind --create-home openwind

COPY --from=builder /dist /tmp/dist
RUN python -m pip install --no-cache-dir /tmp/dist/*.whl \
    && rm -rf /tmp/dist

WORKDIR /var/lib/openwind
USER openwind

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).read()" || exit 1

CMD ["openwind-au", "serve"]
