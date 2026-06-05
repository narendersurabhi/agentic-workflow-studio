FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app \
    PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org pypi.python.org" \
    PIP_DISABLE_PIP_VERSION_CHECK=1
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
RUN pip install --no-cache-dir -e /app/libs/core -e .
CMD ["python", "-m", "app.main"]
