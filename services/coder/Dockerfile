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
COPY services/coder /app/services/coder
WORKDIR /app/services/coder
RUN pip install --no-cache-dir -e /app/libs/core -e .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
