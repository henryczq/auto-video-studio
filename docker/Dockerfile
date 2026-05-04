FROM python:3.12-slim

LABEL maintainer="Auto Video Studio"
LABEL description="自动化视频处理工作台"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY web/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir openai-whisper

RUN playwright install chromium && playwright install-deps chromium

COPY web/backend /app/web/backend
COPY web/frontend /app/web/frontend
COPY core /app/core
COPY config /app/config
COPY publish /app/publish

RUN mkdir -p /app/data /app/videos/web_jobs /app/logs

ENV PYTHONPATH=/app:/app/web/backend
ENV AUTO_CUT_HOST=0.0.0.0
ENV AUTO_CUT_PORT=1894

EXPOSE 1894

WORKDIR /app/web/backend

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "1894"]
