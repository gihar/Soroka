# Installation Guide

This guide covers how to deploy Soroka using Docker (recommended) or directly on your local machine.

## Prerequisites

-   **Docker** & **Docker Compose** (for Docker deployment)
-   **Python 3.11+** (for local deployment)
-   **FFmpeg** installed on the system

## 🐳 Docker Deployment (Recommended)

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd Soroka
    ```

2.  **Create configuration:**
    ```bash
    cp env_example .env
    ```
    Edit `.env` and fill in your API keys. See [Configuration](CONFIGURATION.md) for details.

3.  **Build and Run:**
    ```bash
    docker-compose up -d --build
    ```

4.  **Check Logs:**
    ```bash
    docker-compose logs -f
    ```

## 💻 Local Installation

If you prefer to run without Docker (e.g., for development):

1.  **Install System Dependencies:**
    -   **macOS**: `brew install ffmpeg`
    -   **Ubuntu/Debian**: `sudo apt-get install ffmpeg`

2.  **Create Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Python Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *Note: Some libraries like `pyannote.audio` or `torch` might require specific installation steps depending on your hardware (CUDA/MPS).*

4.  **Configure:**
    ```bash
    cp env_example .env
    # Edit .env
    ```

5.  **Run:**
    ```bash
    python main.py
    ```

## 🍎 Apple Silicon (M1/M2/M3) Optimization

For optimal performance on macOS with Apple Silicon:

1.  Ensure you are using **Python 3.11** (native arm64).
2.  PyTorch should be installed with MPS support (usually automatic with recent versions).
3.  In `.env`, set:
    ```env
    DIARIZATION_DEVICE=mps
    ```
