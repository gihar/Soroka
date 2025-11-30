# Testing Guide - Soroka Meeting Bot

## Overview

This document outlines the testing procedures and quality assurance processes for the Soroka meeting minutes bot. The testing strategy covers manual testing, automated testing (where applicable), and quality assurance procedures.

## Testing Environment Setup

### Prerequisites

- Telegram Bot API token (test bot recommended)
- Access to transcription and LLM services for testing
- Sample audio/video files in various formats
- Test database (separate from production)

### Test Configuration

```bash
# Create test environment
cp env_example .env.test

# Update with test-specific values
TELEGRAM_BOT_TOKEN=test_bot_token
DATABASE_PATH=test_bot.db
# Use sandbox API keys where available
```

## Manual Testing Procedures

### 1. Core Functionality Testing

#### 1.1 Bot Initialization
- **Test Case**: Start bot with `/start` command
- **Expected Result**: Welcome message and main menu displayed
- **Verification**: Check that all buttons work correctly

#### 1.2 File Upload Processing
- **Test Cases**:
  - Upload MP3 audio file (various sizes: 1MB, 50MB, 200MB)
  - Upload WAV audio file
  - Upload MP4 video file
  - Upload MOV video file
  - Upload unsupported file format
- **Expected Results**:
  - Supported files: Processing starts, queue position shown
  - Unsupported files: Clear error message
  - Large files: Proper handling within size limits
- **Verification**: Monitor processing queue and database records

#### 1.3 URL Processing
- **Test Cases**:
  - Google Drive shared link (public)
  - Yandex Disk shared link
  - Invalid URL
  - URL requiring authentication
- **Expected Results**:
  - Valid links: File downloaded and processed
  - Invalid links: Clear error message
  - Auth-required links: Request for public link

### 2. Transcription Quality Testing

#### 2.1 Multi-Provider Testing
- **Test Providers**: Whisper, Groq, Deepgram, Speechmatics
- **Test Files**: Various audio qualities and accents
- **Verification**:
  - Transcription accuracy assessment
  - Processing time measurement
  - Error handling for provider failures

#### 2.2 Speaker Diarization
- **Test Scenarios**:
  - 2-person conversation
  - 3-person meeting
  - 5+ participant meeting
  - Single speaker
  - Poor audio quality
- **Verification**:
  - Speaker identification accuracy
  - Speaker label consistency
  - Handling of unclear audio segments

### 3. Template System Testing

#### 3.1 Smart Template Selection
- **Test Meeting Types**:
  - Daily standup (mentions "yesterday", "today", "blockers")
  - Strategic planning (mentions "strategy", "goals", "vision")
  - Technical discussion (mentions "API", "code", "architecture")
  - Retrospective (mentions "what went well", "improvements")
  - Educational content (mentions "students", "learning", "course")
- **Verification**:
  - Correct template identification
  - Confidence scoring
  - Fallback to manual selection when needed

#### 3.2 Template Application
- **Test Cases**:
  - Apply each built-in template
  - Create custom template
  - Test template variables substitution
  - Test long content handling
- **Verification**:
  - Proper section formatting
  - Variable replacement accuracy
  - Content structure preservation

### 4. Speaker Mapping Testing

#### 4.1 Automatic Speaker Mapping
- **Test Scenarios**:
  - Clear speaker differences (male/female voices)
  - Similar speaker voices
  - Provided participant list matches actual speakers
  - Participant list has extra/missing names
- **Verification**:
  - Mapping accuracy
  - Confidence scoring
  - Request for confirmation when needed

#### 4.2 Speaker Confirmation UI
- **Test Cases**:
  - High confidence mapping (no confirmation needed)
  - Medium confidence (confirmation requested)
  - Low confidence (multiple options provided)
  - User rejects suggestions
- **Verification**:
  - UI clarity and usability
  - Proper state management
  - Processing continuation after confirmation

### 5. LLM Integration Testing

#### 5.1 Multiple Provider Testing
- **Test Providers**: OpenAI GPT-4, Anthropic Claude, YandexGPT
- **Verification**:
  - Protocol generation quality
  - Response time comparison
  - Error handling for provider failures
  - Cost efficiency analysis

#### 5.2 Content Analysis Quality
- **Test Metrics**:
  - Action item identification accuracy
  - Decision extraction completeness
  - Key topic relevance
  - Summary quality
  - Speaker attribution accuracy

### 6. Output Generation Testing

#### 6.1 Telegram Messages
- **Test Cases**:
  - Short protocols (< 4096 chars)
  - Long protocols (> 4096 chars)
  - Special characters and formatting
  - Emoji and unicode handling
- **Verification**:
  - Message splitting correctness
  - Formatting preservation
  - Readability in Telegram

#### 6.2 File Generation
- **Test Cases**:
  - PDF file generation
  - Markdown file generation
  - Mixed output modes
  - File naming conventions
- **Verification**:
  - File format validity
  - Content accuracy
  - File size optimization

### 7. Error Handling Testing

#### 7.1 Input Validation
- **Test Cases**:
  - Malformed URLs
  - Corrupted audio files
  - Exceeding size limits
  - Invalid participant names
- **Verification**:
  - Clear error messages
  - Graceful degradation
  - No system crashes

#### 7.2 API Failure Handling
- **Test Scenarios**:
  - Transcription service unavailable
  - LLM API rate limits
  - Network timeouts
  - Invalid API keys
- **Verification**:
  - Proper error logging
  - User notification
  - Retry logic where appropriate
  - Queue management during failures

### 8. Performance Testing

#### 8.1 Load Testing
- **Test Scenarios**:
  - Multiple simultaneous users
  - Queue processing under load
  - Memory usage monitoring
  - Database performance under load
- **Metrics to Monitor**:
  - Processing time per request
  - Memory usage patterns
  - Queue wait times
  - Database query performance

#### 8.2 Stress Testing
- **Test Cases**:
  - Large file processing (near limits)
  - Maximum queue size
  - Extended operation duration
  - Resource exhaustion scenarios
- **Verification**:
  - OOM protection activation
  - Graceful degradation
  - System recovery after stress

## Quality Assurance Checklist

### Pre-Release Testing

#### Functionality Verification
- [ ] All bot commands work correctly
- [ ] File processing pipeline complete
- [ ] All template types functional
- [ ] Speaker mapping accurate
- [ ] Output generation correct
- [ ] Error handling comprehensive

#### User Experience Testing
- [ ] Interface intuitive and responsive
- [ ] Messages clear and informative
- [ ] Progress indicators accurate
- [ ] Error messages helpful
- [ ] Button interactions smooth

#### Performance Verification
- [ ] Processing times acceptable
- [ ] Memory usage within limits
- [ ] Queue processing efficient
- [ ] Database operations optimized

#### Security and Reliability
- [ ] Input validation comprehensive
- [ ] File handling secure
- [ ] API credentials protected
- [ ] Error logging sufficient
- [ ] System recovery tested

### Regression Testing

#### Core Workflow
- [ ] File upload → transcription → analysis → output
- [ ] Template selection and application
- [ ] Speaker identification and mapping
- [ ] Multi-provider functionality
- [ ] Queue management

#### Feature Integration
- [ ] New features don't break existing functionality
- [ ] Configuration changes work correctly
- [ ] Database migrations successful
- [ ] API integrations stable

## Test Data and Scenarios

### Sample Audio Files

#### File Types for Testing
1. **Clear Audio**: High-quality meeting recording
2. **Noisy Audio**: Background noise, multiple speakers
3. **Various Accents**: Different speaker backgrounds
4. **Meeting Types**: Daily standup, presentation, brainstorm
5. **File Sizes**: 1MB, 50MB, 200MB, 1GB

#### Content Scenarios
1. **Standard Meeting**: Clear agenda, structured discussion
2. **Chaotic Meeting**: Multiple simultaneous speakers
3. **Presentation**: One main speaker with questions
4. **Decision Meeting**: Action items and decisions
5. **Educational Content**: Lecture-style presentation

### Participant Lists for Testing

#### Standard Scenarios
- Small team (2-3 participants)
- Medium team (4-6 participants)
- Large meeting (7+ participants)
- Single speaker
- Unknown/unregistered speakers

### Templates for Testing

#### Built-in Templates
- Daily Standup
- Strategic Planning
- Technical Discussion
- Retrospective
- Educational Lecture
- 1-on-1 Meeting
- Brainstorming Session
- Decision Meeting

#### Custom Templates
- Simple structure
- Complex sections
- Custom variables
- Special formatting

## Automated Testing (Future Implementation)

### Unit Testing Framework
```python
# Example test structure
import pytest
from src.services.processing_service import OptimizedProcessingService

class TestProcessingService:
    async def test_file_validation(self):
        # Test file format validation
        pass

    async def test_transcription_quality(self):
        # Test transcription accuracy
        pass

    async def test_template_selection(self):
        # Test smart template selection
        pass
```

### Integration Tests
- Database operations
- API integrations
- End-to-end workflows
- Error scenarios

### Performance Tests
- Load testing scenarios
- Memory usage profiling
- Database performance
- API response times

## Testing Tools and Utilities

### Monitoring and Debugging
- **Loguru**: Structured logging with context
- **Memory Profiler**: Memory usage monitoring
- **Database Explorer**: Query performance analysis
- **API Monitoring**: Response time and error tracking

### Test Automation Tools
- **pytest**: Unit and integration testing framework
- **Docker**: Isolated test environments
- **GitHub Actions**: CI/CD pipeline testing
- **Postman/Newman**: API testing (if REST endpoints added)

## Bug Reporting and Tracking

### Bug Report Template
```
**Description**: Clear description of the issue
**Steps to Reproduce**:
1. Step 1
2. Step 2
3. Step 3
**Expected Result**: What should happen
**Actual Result**: What actually happened
**Environment**: OS, Python version, etc.
**Logs**: Relevant log entries
**Files**: Sample files that trigger the issue (if applicable)
```

### Priority Classification
- **Critical**: System crashes, data loss, security issues
- **High**: Major functionality broken, poor user experience
- **Medium**: Minor functionality issues, workarounds available
- **Low**: UI improvements, minor optimizations

## Continuous Improvement

### Testing Metrics
- Bug discovery rate
- Test coverage percentage
- Mean time to resolution
- User satisfaction scores
- System uptime and reliability

### Process Optimization
- Regular test case review and updates
- Automation of repetitive testing tasks
- Integration of user feedback into testing scenarios
- Performance benchmarking and optimization

This testing guide serves as the foundation for ensuring Soroka meets high-quality standards and provides reliable service to users.