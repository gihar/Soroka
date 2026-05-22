# Decisions Log -- Improve Protocol Generation Prompts

## Feature Definition of Done
- python -m py_compile passes for both files
- pytest tests/ passes (if tests exist)
- All 3 providers (OpenAI, Anthropic, YandexGPT) pass meeting_agenda/project_list consistently
- All educational template variables have FIELD_SPECIFIC_RULES entries
- System prompt expanded with 4 new sections

## Risks & Mitigations
(Added after risk analysis phase)

## Architectural Decisions

## Decision: Two architectural patterns coexist for providers -- document, do not merge
Date: 2026-03-09
Context: OpenAI and Anthropic use two-stage prompts from src/prompts/prompts.py (build_analysis_prompt + build_generation_prompt). YandexGPT uses the legacy single-stage _build_user_prompt/_build_system_prompt defined in llm_providers.py. Task 2 must fix YandexGPT within its current single-stage architecture; migrating to two-stage is out of scope.
Alternatives considered: Migrate YandexGPT to two-stage (too large for this feature), unify all providers (not requested).

## Decision: Count of missing FIELD_SPECIFIC_RULES is 26, not 25 -- verify with coder
Date: 2026-03-09
Context: Extracted all unique {{ variable }} names from template_library.py and diffed against existing FIELD_SPECIFIC_RULES keys. Found 26 missing entries. Some may be non-educational (e.g., additional_notes, meeting_date). Task 3 description says "25 educational template variables" but actual count differs. Coder should verify exact scope.
Alternatives considered: Accept 25 as stated (would miss some), add all 26 (some may not be educational-specific).
