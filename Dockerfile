# Этап сборки
FROM python:3.11-slim as builder

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "numpy<2" && \
    pip install --no-cache-dir -r requirements.txt

# Финальный этап
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --chown=1000:1000 src/ ./src/
COPY --chown=1000:1000 main.py .
COPY --chown=1000:1000 config.py .
COPY --chown=1000:1000 database.py .
COPY --chown=1000:1000 diarization.py .
COPY --chown=1000:1000 llm_providers.py .
COPY --chown=1000:1000 install.sh .

RUN mkdir -p logs temp cache && \
    chmod +x install.sh && \
    useradd --create-home --shell /bin/bash --uid 1000 bot && \
    chown -R bot:bot /app && \
    mkdir -p /home/bot/.config && \
    chown -R bot:bot /home/bot/.config

ENV MPLCONFIGDIR=/home/bot/.config/matplotlib
ENV PYTHONPATH=/app

USER bot
EXPOSE 8080
CMD ["python", "main.py"]
