# Development Guide - Soroka Meeting Bot

## Project Structure

```
Soroka/
├── src/                          # Main source code
│   ├── bot.py                    # Bot initialization and configuration
│   ├── handlers/                 # Telegram handlers
│   │   ├── message_handlers.py   # Message processing
│   │   ├── callback_handlers.py  # Inline button callbacks
│   │   ├── command_handlers.py   # Bot commands (/start, /settings, etc.)
│   │   └── participants_handlers.py # Participant management
│   ├── models/                   # Data models and schemas
│   │   ├── llm_schemas.py        # LLM request/response schemas
│   │   └── processing.py         # Processing request models
│   ├── prompts/                  # LLM prompts and templates
│   │   └── prompts.py            # Main prompt templates
│   ├── services/                 # Business logic services
│   │   ├── processing_service.py # Meeting processing logic
│   │   ├── speaker_mapping_service.py # Speaker identification
│   │   ├── template_service.py   # Template management
│   │   ├── user_service.py       # User management
│   │   └── template_library.py   # Built-in templates
│   └── utils/                    # Utility functions
│       ├── message_utils.py      # Telegram message formatting
│       ├── text_processing.py    # Text analysis utilities
│       ├── validation_utils.py   # Input validation
│       ├── pdf_converter.py      # PDF generation
│       ├── transcript_formatter.py # Transcript formatting
│       └── context_extraction.py # Context extraction utilities
├── docs/                         # Documentation
├── tests/                        # Test files (if applicable)
├── database.py                   # Database operations
├── llm_providers.py              # LLM provider implementations
├── config.py                     # Configuration management
├── docker-compose.yml            # Docker deployment
├── Dockerfile                    # Docker build configuration
├── env_example                   # Environment variables template
└── requirements.txt              # Python dependencies
```

## Key Components

### 1. Processing Pipeline

The main processing flow is orchestrated by `OptimizedProcessingService`:

1. **File Validation**: Check format, size, and accessibility
2. **Caching Check**: Compute file hash and check for existing results
3. **Transcription**: Convert audio to text using selected provider
4. **Diarization**: Identify and separate speakers
5. **Speaker Mapping**: Map "Speaker 0/1/2..." to real names
6. **Template Selection**: Choose appropriate template (smart or manual)
7. **Content Generation**: Generate protocol using LLM
8. **Formatting**: Format and clean the final output

### 2. Smart Template Selection

The `SmartTemplateSelector` uses a hybrid approach:

```python
# Selection Algorithm:
1. Extract meeting transcript (first 1500 chars)
2. Generate text embedding using sentence-transformers
3. Calculate cosine similarity with all templates
4. Apply meeting classifier (keyword-based)
5. Boost scores based on:
   - User history (30% boost)
   - Category match (15% boost)
   - Meeting type detection
6. Return top recommendation
```

### 3. Speaker Mapping Service

The `SpeakerMappingService` handles speaker identification:

- **Input**: Transcript with speaker labels, participant list
- **Process**: LLM-powered matching with confidence scoring
- **Output**: Speaker name mapping or confirmation request
- **UI**: Interactive confirmation for low-confidence matches

### 4. Template System

Templates are structured with sections and variables:

```python
# Template Structure:
{
    "name": "Daily Standup",
    "category": "daily",
    "description": "Daily team meeting template",
    "sections": [
        {
            "title": "Участники",
            "content": "Participants: {participants}"
        },
        {
            "title": "Статус команды",
            "content": "Team status updates and blockers"
        }
    ],
    "variables": ["participants"]
}
```

## Development Setup

### Prerequisites

- Python 3.11+
- SQLite 3
- FFmpeg (for audio processing)
- Docker (optional, for containerized deployment)

### Local Development

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd Soroka
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```bash
   cp env_example .env
   # Edit .env with your API keys
   ```

3. **Initialize database**:
   ```bash
   python -c "import asyncio; from database import Database; asyncio.run(Database().init_db())"
   ```

4. **Run the bot**:
   ```bash
   python src/bot.py
   ```

### Docker Development

```bash
# Build and run
docker-compose up --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Configuration

### Environment Variables

Key environment variables in `.env`:

```bash
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token

# LLM Providers
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
YANDEX_API_KEY=your_yandex_key

# Transcription Services
WHISPER_API_KEY=your_whisper_key
GROQ_API_KEY=your_groq_key
DEEPGRAM_API_KEY=your_deepgram_key

# Database
DATABASE_PATH=bot.db

# Processing
MAX_QUEUE_SIZE=10
WORKER_COUNT=2
OOM_THRESHOLD_MB=1024
```

## Testing

### Manual Testing Workflow

1. **Basic File Processing**:
   - Send audio file to bot
   - Verify transcription quality
   - Check speaker identification
   - Validate protocol generation

2. **Template Selection**:
   - Test with various meeting types
   - Verify smart selection accuracy
   - Test custom template creation

3. **Error Handling**:
   - Test with invalid files
   - Test network failures
   - Test API rate limits

### Performance Testing

Monitor:
- Memory usage during processing
- Queue processing time
- API response times
- Database query performance

## Code Style and Best Practices

### Python Standards
- Use type hints for all functions
- Follow PEP 8 formatting
- Use async/await for I/O operations
- Implement proper error handling

### Logging
- Use `loguru` for structured logging
- Include context (user_id, request_id) in logs
- Log errors with stack traces
- Monitor performance metrics

### Database
- Use async SQLite operations
- Implement connection pooling
- Use transactions for data consistency
- Include proper error handling

### API Integration
- Implement retry logic with exponential backoff
- Handle rate limiting gracefully
- Validate API responses
- Cache results when appropriate

## Common Development Tasks

### Adding New Transcription Provider

1. Create provider class in `llm_providers.py`
2. Implement `transcribe()` method
3. Add to provider registry
4. Update configuration
5. Add tests

### Creating New Template

1. Define template in `template_library.py`
2. Add to appropriate category
3. Test template selection
4. Update documentation

### Adding New LLM Provider

1. Implement provider interface in `llm_providers.py`
2. Add configuration options
3. Update prompt formatting
4. Test integration

### Extending Speaker Mapping

1. Modify `speaker_mapping_service.py`
2. Add new matching algorithms
3. Update confirmation UI
4. Test accuracy improvements

## Deployment

### Production Deployment

1. **Environment Setup**:
   - Configure production environment variables
   - Set up monitoring and logging
   - Configure database backups

2. **Docker Deployment**:
   ```bash
   # Production compose file
   docker-compose -f docker-compose.prod.yml up -d
   ```

3. **Monitoring**:
   - Monitor bot health
   - Track processing queue size
   - Monitor API usage and costs
   - Set up alerts for errors

### Performance Optimization

- **Caching**: Implement Redis for result caching
- **Database**: Optimize queries and add indexes
- **Processing**: Use worker pools for CPU-intensive tasks
- **Memory**: Implement streaming for large files

## Troubleshooting

### Common Issues

1. **Memory Errors**:
   - Check OOM protection settings
   - Monitor file sizes
   - Optimize audio processing

2. **API Failures**:
   - Verify API keys and quotas
   - Check rate limiting
   - Review error logs

3. **Database Issues**:
   - Check database permissions
   - Verify schema migrations
   - Monitor connection pool

4. **Performance Issues**:
   - Profile processing pipeline
   - Optimize database queries
   - Check resource utilization

### Debugging

- Use structured logging with correlation IDs
- Implement health check endpoints
- Monitor queue processing
- Track API response times

## Contributing

### Pull Request Process

1. Fork repository
2. Create feature branch
3. Implement changes with tests
4. Update documentation
5. Submit pull request with description

### Code Review Checklist

- [ ] Code follows style guidelines
- [ ] Tests pass and cover new functionality
- [ ] Documentation is updated
- [ ] Error handling is comprehensive
- [ ] Performance impact is considered
- [ ] Security implications are reviewed

## Future Development

### Planned Enhancements

1. **Advanced Analytics**:
   - Meeting pattern analysis
   - Speaker participation metrics
   - Template effectiveness tracking

2. **Integration Features**:
   - Calendar integration
   - CRM/Project management integration
   - Multi-language support

3. **AI Improvements**:
   - Custom model fine-tuning
   - Advanced sentiment analysis
   - Real-time processing

### Technical Debt

- Refactor monolithic services
- Implement comprehensive test suite
- Add monitoring and alerting
- Optimize database schema
- Improve error handling consistency