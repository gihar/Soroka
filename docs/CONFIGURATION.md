# Configuration Guide

Soroka is configured via environment variables, typically defined in a `.env` file.

## Core Settings

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `TELEGRAM_TOKEN` | Your Telegram Bot Token from @BotFather | Yes | - |
| `DATABASE_URL` | Database connection string | No | `sqlite:///bot.db` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | No | `INFO` |

## LLM Providers

You must configure at least one LLM provider.

### OpenAI
```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo
```

### Anthropic (Claude)
```env
ANTHROPIC_API_KEY=sk-ant-...
```

### Yandex GPT
```env
YANDEX_API_KEY=...
YANDEX_FOLDER_ID=...
```

## Transcription & Diarization

Control how audio is processed.

| Variable | Description | Options | Default |
|----------|-------------|---------|---------|
| `TRANSCRIPTION_MODE` | Transcription engine | `local`, `cloud`, `hybrid`, `speechmatics`, `leopard` | `local` |
| `ENABLE_DIARIZATION` | Enable speaker separation | `true`, `false` | `false` |
| `DIARIZATION_PROVIDER` | Diarization engine | `whisperx`, `pyannote`, `picovoice` | `whisperx` |

### Cloud Providers Keys
- `GROQ_API_KEY`: For fast cloud transcription via Groq.
- `SPEECHMATICS_API_KEY`: For Speechmatics API.
- `DEEGRAM_API_KEY`: For Deepgram API.
- `PICOVOICE_ACCESS_KEY`: For Picovoice (Leopard/Falcon).

## Performance & Limits

```env
# Max file size for Telegram uploads (bytes)
TELEGRAM_MAX_FILE_SIZE=20971520  # 20MB

# Max file size for external links (bytes)
MAX_EXTERNAL_FILE_SIZE=52428800  # 50MB

# OOM Protection
OOM_MAX_MEMORY_PERCENT=90.0
```

## Advanced Features

- `ENABLE_SPEAKER_MAPPING`: Enable intelligent mapping of speakers to known participants (default: `true`).
- `ENABLE_PROMPT_CACHING`: Use prompt caching to save costs (default: `true`).
- `ENABLE_CLEANUP`: Auto-delete temp files (default: `true`).
