# 🤖 Soroka - Intelligent Meeting Minutes Bot

Soroka is an advanced Telegram bot designed to automatically generate structured meeting minutes from audio and video recordings. It leverages state-of-the-art AI technologies for transcription, diarization (speaker identification), and analysis.

[🇷🇺 Русская версия](README_ru.md)

## 🚀 Key Features

-   **Multi-Provider Transcription**: Support for **OpenAI Whisper**, **Groq**, **Deepgram**, **Speechmatics**, and local **Picovoice Leopard**.
-   **Smart Diarization**: Automatically identifies and separates speakers using **WhisperX**, **Pyannote**, or **Picovoice**.
-   **Intelligent Analysis**:
    -   Extracts key decisions, action items, and agreements.
    -   Analyzes speaker contributions and roles.
    -   Detects meeting types automatically.
-   **Flexible Templates**: Built-in templates for various meeting types (Daily, Strategic, Technical, etc.) plus custom template support.
-   **Robust Architecture**:
    -   OOM (Out of Memory) protection.
    -   Flood control and rate limiting.
    -   Automatic file cleanup.
-   **Broad Format Support**: Handles all popular audio/video formats (MP3, WAV, MP4, MOV, etc.) and direct links from Google Drive/Yandex Disk.

## 📚 Documentation

-   [**Installation Guide**](docs/INSTALLATION.md) - Deploy with Docker or run locally.
-   [**Configuration**](docs/CONFIGURATION.md) - Detailed description of all environment variables.
-   [**Usage Guide**](docs/USAGE.md) - How to use the bot, commands, and workflows.
-   [**Troubleshooting**](docs/TROUBLESHOOTING.md) - Solutions for common issues.

## ⚡ Quick Start (Docker)

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd Soroka
    ```

2.  **Configure environment:**
    ```bash
    cp env_example .env
    # Edit .env with your API keys (Telegram, OpenAI/Anthropic, etc.)
    ```

3.  **Run with Docker Compose:**
    ```bash
    docker-compose up -d
    ```

The bot will be available in your Telegram chat. Send `/start` to begin!

## 🛠 Tech Stack

-   **Core**: Python 3.11+, Aiogram 3.x
-   **Database**: SQLite (async)
-   **AI/ML**: OpenAI GPT-4, Anthropic Claude, Whisper, Pyannote.audio
-   **Infrastructure**: Docker, Docker Compose

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

MIT License
