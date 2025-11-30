# 🤖 Soroka - Intelligent Meeting Minutes Bot

![Production Ready](https://img.shields.io/badge/status-production%20ready-brightgreen)
![Implementation](https://img.shields.io/badge/implementation-95%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-blue)

Soroka is an advanced Telegram bot designed to automatically generate structured meeting minutes from audio and video recordings. It leverages state-of-the-art AI technologies for transcription, diarization (speaker identification), and analysis.

[🇷🇺 Русская версия](README_ru.md)

## 🚀 Key Features

-   **Multi-Provider Transcription**: Support for **OpenAI Whisper**, **Groq**, **Deepgram**, **Speechmatics**, and local **Picovoice Leopard**.
-   **Smart Diarization**: Automatically identifies and separates speakers using **WhisperX**, **Pyannote**, or **Picovoice**.
-   **Intelligent Analysis**:
    -   Extracts key decisions, action items, and agreements.
    -   Analyzes speaker contributions and roles.
    -   Detects meeting types automatically using ML-powered classification.
    -   Two-stage processing: Analysis followed by generation for improved quality.
-   **Advanced Template System**:
    -   Built-in templates for various meeting types (Daily, Strategic, Technical, Scrum, Educational, etc.).
    - Smart template selection using hybrid keyword matching + vector similarity.
    - Custom template support with rich text formatting.
    - Educational templates for lectures, training, and consultations.
    - Auto-updating system templates.
-   **Robust Architecture**:
    -   OOM (Out of Memory) protection.
    -   Flood control and rate limiting.
    -   Automatic file cleanup.
-   **Broad Format Support**: Handles all popular audio/video formats (MP3, WAV, MP4, MOV, etc.) and direct links from Google Drive/Yandex Disk.
-   **Speaker Management**: AI-powered speaker identification and mapping using participant lists with confirmation UI.
-   **Flexible Output**: Telegram messages, PDF files, and Markdown files with customizable output modes.

## 📚 Documentation

### User Documentation
-   [**Installation Guide**](docs/INSTALLATION.md) - Deploy with Docker or run locally.
-   [**Configuration**](docs/CONFIGURATION.md) - Detailed description of all environment variables.
-   [**Usage Guide**](docs/USAGE.md) - How to use the bot, commands, and workflows.
-   [**Troubleshooting**](docs/TROUBLESHOOTING.md) - Solutions for common issues.

### Technical Documentation
-   [**Development Guide**](DEVELOPMENT.md) - Development setup, architecture, and contribution guidelines.
-   [**Processing Pipeline**](docs/processing_pipeline.md) - Technical overview of the meeting processing workflow.
-   [**Testing Guide**](TESTING.md) - Comprehensive testing procedures and quality assurance.
-   [**Implementation Status**](IMPLEMENTATION_STATUS.md) - Current project status and implementation progress.

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
