FROM python:3.13-slim AS builder
WORKDIR /app
ENV PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org pypi.python.org" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY libs/core /app/libs/core
COPY libs/framework /app/libs/framework
COPY libs/tools /app/libs/tools
COPY config /app/config
COPY services/policy /app/services/policy
WORKDIR /app/services/policy
RUN uv pip install --system --no-cache -e /app/libs/core -e .

FROM python:3.13-slim
WORKDIR /app/services/policy
ENV PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app
CMD ["python", "-m", "app.main"]
