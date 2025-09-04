# Этап сборки
FROM python:3.11-slim AS builder

# Установка build-зависимостей в одном слое
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && apt-get autoremove -y

# Создание виртуального окружения
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Выбор набора зависимостей
ARG FLAVOR=full
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Установка зависимостей
COPY requirements.txt requirements.txt
COPY requirements-lite.txt requirements-lite.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-compile "numpy<2" && \
    if [ "$FLAVOR" = "lite" ]; then \
        echo "Installing lite requirements" && \
        pip install --no-cache-dir --no-compile -r requirements-lite.txt ; \
    else \
        echo "Installing full requirements" && \
        pip install --no-cache-dir --no-compile -r requirements.txt ; \
    fi

# Финальный этап - используем тот же базовый образ
FROM python:3.11-slim

# Установка только runtime зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
    && apt-get clean \
    && apt-get autoremove -y

# Копирование виртуального окружения
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Копирование файлов приложения
COPY --chown=1000:1000 src/ ./src/
COPY --chown=1000:1000 main.py .
COPY --chown=1000:1000 config.py .
COPY --chown=1000:1000 database.py .
COPY --chown=1000:1000 diarization.py .
COPY --chown=1000:1000 llm_providers.py .

# Создание пользователя и настройка прав в одном слое
RUN mkdir -p logs temp cache && \
    useradd --create-home --shell /bin/bash --uid 1000 bot --no-log-init && \
    chown -R bot:bot /app && \
    mkdir -p /home/bot/.config && \
    chown -R bot:bot /home/bot/.config

ENV MPLCONFIGDIR=/home/bot/.config/matplotlib
ENV PYTHONPATH=/app

USER bot
EXPOSE 8080
CMD ["python", "main.py"]
