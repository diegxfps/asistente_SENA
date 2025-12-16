FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# instalar deps primero (mejor cache)
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
 && pip config unset global.require-hashes || true \
 && pip install --no-cache-dir -i https://pypi.org/simple -r requirements.txt

# copiar tu app y datos
COPY app ./app
COPY app data ./data
COPY storage_simple ./storage_simple

ENV PYTHONUNBUFFERED=1
ENV PORT=8000
EXPOSE 8000
CMD ["python", "-m", "app.webhook"]
