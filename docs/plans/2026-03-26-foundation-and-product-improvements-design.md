# Soroka: Foundation + Product Improvements Design

**Date:** 2026-03-26
**Status:** Approved
**Author:** Claude + timchenko

## Context

Soroka — Telegram-бот для автоматической генерации протоколов встреч из аудио/видео.
Текущее состояние: ~31K строк Python, 7 тест-файлов (~5% покрытия), нет CI/CD,
несколько монолитных файлов >1000 строк, глобальные синглтоны вместо DI.

Цель: заложить фундамент (фаза A) для безопасного развития, затем улучшить продукт (фаза C).

## Phase A: Foundation

### A1. CI/CD Pipeline + Linting + Type Checking
- pyproject.toml (ruff, mypy, pytest config)
- .github/workflows/ci.yml
- Makefile (lint, test, check)
- .pre-commit-config.yaml
- requirements-dev.txt

### A2. Split callback_handlers.py (2,216 -> 7 files)
Target: src/handlers/callbacks/{llm,template,template_mgmt,settings,processing,speaker_mapping}_callbacks.py + helpers.py

### A3. Split processing_service.py (1,942 -> 4 files)
Target: src/services/processing/{processing_service,protocol_formatter,llm_generation_service,processing_history}.py

### A4. Split llm_providers.py (1,201 -> 6 files)
Target: src/llm/{base,manager,json_utils,prompt_builders}.py + src/llm/providers/{openai,anthropic,yandex}_provider.py

### A5. Move database.py to src/ + Repository Pattern
Target: src/database/{database,user_repo,template_repo,feedback_repo,metrics_repo,queue_repo}.py

### A6. Move config.py to src/
Target: src/config.py with root-level re-export

### A7. Tests for critical paths (target 40%+ coverage)
- Database CRUD, JSON parsing, LLM fallback, processing happy path

## Phase C: Product Improvements

### C1. Extract prompts to YAML files
### C2. LLM streaming responses
### C3. Feedback loop + analytics dashboard
### C4. UX improvements (inline buttons, progress bar)

## Execution Order

A1 -> A6 -> A5 -> A4 -> A2 -> A3 -> A7 -> C1 -> C2 -> C3 -> C4

## Verification

After each step: make lint, make test, manual bot test, backward-compatible imports.
