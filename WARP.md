# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview
Soroka is an enhanced Telegram bot for creating structured meeting protocols from audio/video recordings using AI technologies. It supports multiple LLM providers (OpenAI GPT, Anthropic Claude, Yandex GPT), speaker diarization, and custom templating.

## Development Commands

### Environment Setup
```bash
# Initial setup with automatic dependency installation
chmod +x install.sh && ./install.sh

# Manual Python environment setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration setup
cp .env.example .env
# Edit .env with your API keys and tokens
```

### Running the Bot
```bash
# Standard local run
python main.py

# Module-based run
python -m main

# Docker development environment
chmod +x docker-run.sh && ./docker-run.sh

# Docker Compose for production-like environment
docker-compose up --build -d
```

### Development Tools
```bash
# View Docker logs
docker-compose logs -f

# Restart services
docker-compose restart

# Stop services
docker-compose down

# Check container status
docker-compose ps

# Monitor resource usage
docker stats
```

### Database Operations
```bash
# Database is automatically initialized on first run
# SQLite database file: bot.db
# View database structure or data with any SQLite tool
sqlite3 bot.db ".schema"
```

## High-Level Architecture

### Core System Design
This is a **modular, service-oriented architecture** with strong emphasis on reliability and performance:

**Main Components:**
- **Entry Point**: `main.py` - Application bootstrap with health checks
- **Bot Core**: `src/bot.py` - Enhanced bot with reliability middleware
- **Service Layer**: Specialized services for different domains
- **Reliability System**: Circuit breakers, rate limiting, health monitoring
- **Performance Layer**: Async optimization, caching, memory management

### Key Architectural Patterns

**1. Service-Oriented Architecture**
```
src/services/
├── base_processing_service.py    # Core processing logic
├── enhanced_llm_service.py       # LLM integration with fallbacks
├── file_service.py               # File handling and validation
├── transcription_service.py      # Audio/video transcription
├── template_service.py           # Template management
├── user_service.py              # User management
└── url_service.py               # External file downloading
```

**2. Reliability First Design**
```
src/reliability/
├── circuit_breaker.py           # Prevent cascading failures
├── rate_limiter.py             # Protect against overload
├── health_check.py             # System health monitoring
├── retry.py                    # Smart retry mechanisms
└── middleware.py               # Request/response middleware
```

**3. Performance Optimization Layer**
```
src/performance/
├── async_optimization.py       # Concurrent processing
├── cache_system.py            # Intelligent caching (3-10x speedup)
├── memory_management.py       # Resource optimization
└── metrics.py                 # Performance monitoring
```

**4. Handler-Based Request Processing**
```
src/handlers/
├── command_handlers.py         # Bot commands (/start, /help, etc.)
├── callback_handlers.py        # Inline button interactions
├── message_handlers.py         # File processing workflow
├── template_handlers.py        # Template CRUD operations
└── admin_handlers.py          # Administrative functions
```

### Service Dependencies and Data Flow

**File Processing Pipeline:**
1. **FileService** → validates and handles file uploads (Telegram/URLs)
2. **TranscriptionService** → converts audio/video to text (local/cloud)
3. **DiarizationService** → separates speakers (WhisperX/Pyannote/Picovoice)
4. **EnhancedLLMService** → generates structured protocols
5. **TemplateService** → applies user templates with Jinja2

**Critical Service Interactions:**
- **Processing Service** orchestrates the entire pipeline with error recovery
- **Cache System** stores transcription results and LLM responses
- **Health Checker** monitors all service dependencies
- **Rate Limiter** prevents API exhaustion

### Configuration Architecture

**Environment-Based Configuration** (`config.py`):
- **LLM Providers**: OpenAI, Anthropic, Yandex GPT integration
- **Transcription Modes**: local (Whisper), cloud (Groq), hybrid
- **Diarization Options**: WhisperX, Pyannote, Picovoice
- **Performance Tuning**: device selection, compute types, file limits

**Critical Settings:**
- `ENABLE_DIARIZATION`: Speaker separation (disabled by default for stability)
- `TRANSCRIPTION_MODE`: Processing strategy (hybrid recommended)
- `SSL_VERIFY`: Corporate network compatibility
- `MAX_FILE_SIZE`: Per-source size limits

### Database Schema

**SQLite-based persistence** (`database.py`):
- **users**: User preferences and LLM provider selection
- **templates**: Custom and default protocol templates
- **processing_history**: Complete audit trail with transcriptions

### External Integrations

**AI/ML Services:**
- **OpenAI Whisper**: Local transcription (requires ffmpeg)
- **WhisperX**: Enhanced transcription with diarization
- **Groq**: Cloud transcription API
- **Picovoice**: Commercial diarization service

**File Sources:**
- **Telegram Bot API**: Direct file uploads (20MB limit)
- **Google Drive**: Public link file downloads
- **Yandex.Disk**: Public link file downloads
- **General URLs**: HTTP/HTTPS file fetching

## Development Notes

### Error Handling Strategy
- **Circuit Breakers** prevent cascade failures between services
- **Fallback Mechanisms** ensure degraded functionality vs complete failure
- **Smart Retries** with exponential backoff for transient errors
- **Health Monitoring** provides real-time system status

### Performance Considerations
- **Async-First Design**: All I/O operations are non-blocking
- **Intelligent Caching**: Transcription and LLM results cached for reuse
- **Memory Management**: Automatic cleanup of temporary files and models
- **Concurrent Processing**: Multiple files can be processed simultaneously

### Testing & Monitoring
- **Health Checks**: `/health` command shows system status
- **Performance Metrics**: `/performance` shows processing statistics
- **Admin Commands**: Administrative interface for system management
- **Comprehensive Logging**: Structured logs with Loguru

### Deployment Considerations
- **Docker-Ready**: Complete containerization with health checks
- **Environment Isolation**: All secrets via environment variables
- **Graceful Shutdown**: Proper cleanup on termination signals
- **Resource Limits**: Configurable memory and CPU constraints

### Common Development Tasks

**Adding New LLM Provider:**
1. Implement `LLMProvider` interface in `llm_providers.py`
2. Add configuration options to `config.py`
3. Update `EnhancedLLMService` provider registry
4. Test with health check system

**Adding New File Source:**
1. Extend `FileService` with new download method
2. Add URL pattern recognition
3. Update file validation logic
4. Test with different file sizes and types

**Extending Templates:**
1. Add new variables to template system
2. Update LLM prompts to extract new information
3. Test with existing and new templates
4. Update documentation

The codebase prioritizes **reliability over performance** and **maintainability over brevity**, with comprehensive error handling and monitoring throughout all components.
