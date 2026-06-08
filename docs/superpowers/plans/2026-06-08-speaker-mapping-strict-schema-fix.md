# Speaker-Mapping Strict-Schema Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the speaker↔participant confirmation UI by making `SpeakerMappingSchema` valid for OpenAI strict Structured Outputs, hardening the schema generator against the whole class of bug, and making a hard LLM-mapping failure loud instead of silent.

**Architecture:** Three coupled changes. (1) Add `extra="forbid"` to `SpeakerMappingSchema` so Pydantic emits `additionalProperties: false` at the schema root. (2) Add a recursive pass in `get_json_schema` that locks down every object node for strict mode, without clobbering typed `Dict` maps. (3) Convert the silent `return {}` on a hard LLM call error into a typed `SpeakerMappingLLMError` that `map_speakers_to_participants` logs with a greppable marker and degrades gracefully.

**Tech Stack:** Python 3, Pydantic v2 (2.12.5), pytest (`asyncio_mode = "auto"`), loguru, ruff. Tests run with the project venv at `.venv/`.

**Spec:** `docs/superpowers/specs/2026-06-08-speaker-mapping-strict-schema-fix-design.md`

---

## File Structure

- `src/models/llm_schemas.py` — **modify**. Add `Config: extra = "forbid"` to `SpeakerMappingSchema` (~line 100); add `enforce_additional_properties_false` pass inside `get_json_schema` (function at lines 145-212).
- `src/services/speaker_mapping_service.py` — **modify**. Add `SpeakerMappingLLMError` (module top, after imports ~line 14); raise it from the two silent-`return {}` points in `_call_llm_for_mapping` (JSON-parse path ~577-581, generic `except` ~600-602); add a dedicated `except SpeakerMappingLLMError` branch in `map_speakers_to_participants` (~before line 91).
- `tests/test_llm_schemas_strict.py` — **create**. Strict-compliance schema tests (Parts 1 & 2).
- `tests/test_speaker_mapping_failure.py` — **create**. Loud-failure behaviour test (Part 3).

All test commands assume the project venv. Either activate it (`source .venv/bin/activate`) or prefix with `.venv/bin/`. This plan uses the `.venv/bin/` prefix form.

---

## Task 1: Strict-schema compliance (Parts 1 & 2)

**Files:**
- Modify: `src/models/llm_schemas.py` (`SpeakerMappingSchema` ~line 100; `get_json_schema` lines 145-212)
- Test: `tests/test_llm_schemas_strict.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_schemas_strict.py`:

```python
"""Strict Structured Outputs schema compliance.

OpenAI/Azure strict mode requires `additionalProperties: false` on every object
schema node (including the root) whenever `strict: true` is sent. SpeakerMappingSchema
historically lacked this at the root, which made the speaker-mapping LLM call fail
with HTTP 400 and silently disabled the speaker-mapping confirmation UI.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _all_predefined_schemas():
    from src.models import llm_schemas

    names = [n for n in dir(llm_schemas) if n.endswith("_SCHEMA")]
    return [(n, getattr(llm_schemas, n)) for n in names]


def test_speaker_mapping_schema_root_is_closed():
    from src.models.llm_schemas import SPEAKER_MAPPING_SCHEMA

    assert SPEAKER_MAPPING_SCHEMA["strict"] is True
    assert SPEAKER_MAPPING_SCHEMA["schema"].get("additionalProperties") is False


@pytest.mark.parametrize("name,schema", _all_predefined_schemas())
def test_all_strict_schema_roots_are_closed(name, schema):
    if schema.get("strict") is True:
        root = schema["schema"]
        assert root.get("additionalProperties") is False, (
            f"{name}: strict schema root must set additionalProperties=false"
        )


def test_dict_fields_keep_typed_additional_properties():
    """Dict[str, T] maps must keep their typed additionalProperties, NOT be
    overwritten with false (that would forbid the dynamic keys the LLM fills)."""
    from src.models.llm_schemas import SPEAKER_MAPPING_SCHEMA

    props = SPEAKER_MAPPING_SCHEMA["schema"]["properties"]
    for field in ("speaker_mappings", "confidence_scores"):
        ap = props[field].get("additionalProperties")
        assert isinstance(ap, dict), f"{field} should keep a typed additionalProperties"
        assert ap is not False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_llm_schemas_strict.py -v`
Expected: `test_speaker_mapping_schema_root_is_closed` FAILS (root `additionalProperties` is missing → `None is False` → AssertionError); the parametrized case for `SPEAKER_MAPPING_SCHEMA` FAILS for the same reason. The `test_dict_fields_keep_typed_additional_properties` test PASSES already (Dict fields are untouched today).

- [ ] **Step 3: Implement Part 1 — close the SpeakerMappingSchema root**

In `src/models/llm_schemas.py`, add a `Config` to `SpeakerMappingSchema`. The class currently ends at the `mapping_notes` field:

```python
    unmapped_speakers: List[str] = Field(
        description="Список speaker_id (например, SPEAKER_3) с уверенностью < 0.7, которых не удалось надежно сопоставить с участниками"
    )
    mapping_notes: str = Field(description="Заметки по сопоставлению и определению типа встречи")

    class Config:
        extra = "forbid"
```

(Add the `class Config: extra = "forbid"` block immediately after the `mapping_notes` field, matching every other schema in this module.)

- [ ] **Step 4: Implement Part 2 — harden `get_json_schema`**

In `src/models/llm_schemas.py`, inside `get_json_schema`, the body currently ends:

```python
    fix_required_fields(schema)

    # OpenAI требует определенный формат
    return {
        "name": schema.get("title", model_class.__name__),
        "schema": schema,
        "strict": True
    }
```

Replace that tail with a recursive lock-down pass added before the return:

```python
    def enforce_additional_properties_false(node: Dict[str, Any]) -> None:
        """Strict Structured Outputs требует additionalProperties:false на КАЖДОМ
        объектном узле (включая корень). Проставляем его рекурсивно, НЕ трогая
        узлы, где additionalProperties уже задан — это типизированные Dict-карты
        вида {"additionalProperties": {"type": "string"}}, которые провайдер
        принимает и которые нужны для динамических ключей.
        """
        if not isinstance(node, dict):
            return

        if node.get("type") == "object" and "additionalProperties" not in node:
            node["additionalProperties"] = False

        properties = node.get("properties")
        if isinstance(properties, dict):
            for child in properties.values():
                enforce_additional_properties_false(child)

        defs = node.get("$defs")
        if isinstance(defs, dict):
            for child in defs.values():
                enforce_additional_properties_false(child)

        items = node.get("items")
        if isinstance(items, dict):
            enforce_additional_properties_false(items)

    fix_required_fields(schema)
    enforce_additional_properties_false(schema)

    # OpenAI требует определенный формат
    return {
        "name": schema.get("title", model_class.__name__),
        "schema": schema,
        "strict": True
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_llm_schemas_strict.py -v`
Expected: all tests PASS (root `additionalProperties` is now `False` for `SPEAKER_MAPPING_SCHEMA` and every strict schema; Dict fields still carry typed `additionalProperties`).

- [ ] **Step 6: Commit**

```bash
git add src/models/llm_schemas.py tests/test_llm_schemas_strict.py
git commit -m "fix(schemas): close SpeakerMappingSchema root for strict Structured Outputs

SpeakerMappingSchema was the only schema without extra=forbid, so its
strict response_format lacked additionalProperties:false at the root and
OpenAI rejected the mapping call with HTTP 400 — silently disabling the
speaker-mapping confirmation UI. Add the Config and harden get_json_schema
to enforce additionalProperties:false on every object node (without
clobbering typed Dict maps), so no future strict schema can regress."
```

---

## Task 2: Loud failure on LLM mapping error (Part 3)

**Files:**
- Modify: `src/services/speaker_mapping_service.py` (exception class ~line 14; `_call_llm_for_mapping` ~577-581 and ~600-602; `map_speakers_to_participants` ~before line 91)
- Test: `tests/test_speaker_mapping_failure.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_speaker_mapping_failure.py`:

```python
"""The speaker-mapping LLM call must fail LOUDLY, not silently.

A hard LLM/API error (e.g. HTTP 400 invalid schema) must be distinguishable from
a genuinely-empty mapping. The service raises SpeakerMappingLLMError internally and
map_speakers_to_participants logs a greppable marker, then degrades to ({}, "general")
so the protocol still generates.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_mapping_llm_failure_is_loud_and_degrades(monkeypatch):
    from loguru import logger
    from src.services.speaker_mapping_service import (
        SpeakerMappingService,
        SpeakerMappingLLMError,
    )

    service = SpeakerMappingService()

    # Force a non-empty speakers_info so we reach the LLM call, and a trivial prompt.
    monkeypatch.setattr(
        service,
        "_extract_speakers_info",
        lambda *a, **k: [{"speaker": "SPEAKER_1", "samples": ["привет"]}],
    )
    monkeypatch.setattr(service, "_build_mapping_prompt", lambda *a, **k: "prompt")

    async def _raise(*a, **k):
        raise SpeakerMappingLLMError("HTTP 400 invalid schema")

    monkeypatch.setattr(service, "_call_llm_for_mapping", _raise)

    # Capture loguru ERROR output.
    records = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        mapping, meeting_type = await service.map_speakers_to_participants(
            diarization_data={"speakers": ["SPEAKER_1"], "segments": []},
            participants=[{"name": "Иван Петров", "role": "PM"}],
            transcription_text="...",
            llm_provider="openai",
        )
    finally:
        logger.remove(sink_id)

    assert mapping == {}
    assert meeting_type == "general"
    assert any("SPEAKER_MAPPING_LLM_FAILED" in str(r) for r in records), (
        "hard LLM failure must be logged with the SPEAKER_MAPPING_LLM_FAILED marker"
    )


@pytest.mark.asyncio
async def test_empty_mapping_is_not_treated_as_failure(monkeypatch):
    """A successful call returning no confident matches is NOT a failure: no marker."""
    from loguru import logger
    from src.services.speaker_mapping_service import SpeakerMappingService

    service = SpeakerMappingService()
    monkeypatch.setattr(
        service,
        "_extract_speakers_info",
        lambda *a, **k: [{"speaker": "SPEAKER_1", "samples": ["привет"]}],
    )
    monkeypatch.setattr(service, "_build_mapping_prompt", lambda *a, **k: "prompt")

    async def _empty(*a, **k):
        return {"meeting_type": "business", "speaker_mappings": {}}

    monkeypatch.setattr(service, "_call_llm_for_mapping", _empty)

    records = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        mapping, meeting_type = await service.map_speakers_to_participants(
            diarization_data={"speakers": ["SPEAKER_1"], "segments": []},
            participants=[{"name": "Иван Петров", "role": "PM"}],
            transcription_text="...",
            llm_provider="openai",
        )
    finally:
        logger.remove(sink_id)

    assert mapping == {}
    assert meeting_type == "business"
    assert not any("SPEAKER_MAPPING_LLM_FAILED" in str(r) for r in records)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_speaker_mapping_failure.py -v`
Expected: `test_mapping_llm_failure_is_loud_and_degrades` FAILS at import — `cannot import name 'SpeakerMappingLLMError'` (the exception does not exist yet). The second test cannot run either due to the import in the first test's body, but it targets the same module.

- [ ] **Step 3: Define the typed exception**

In `src/services/speaker_mapping_service.py`, after the imports block (the `from src.models.llm_schemas import SPEAKER_MAPPING_SCHEMA` line, ~line 13) and before `class SpeakerMappingService`, add:

```python
class SpeakerMappingLLMError(Exception):
    """Жёсткий сбой LLM-вызова сопоставления (ошибка API / схемы / парсинга).

    Отличает реальный сбой вызова от легитимного пустого результата, когда LLM
    честно вернул отсутствие сопоставлений. Жёсткий сбой логируется громко и
    приводит к мягкой деградации, а не к молчаливому пустому маппингу.
    """
```

- [ ] **Step 4: Raise the exception from the two silent points in `_call_llm_for_mapping`**

In `_call_llm_for_mapping`, the JSON-parse failure currently swallows the error:

```python
                try:
                    result = safe_json_parse(content, context="SpeakerMappingService LLM response")
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error(f"❌ Не удалось распарсить JSON ответа от LLM для маппинга спикеров: {e}")
                    return {}
```

Change the `return {}` to a raise:

```python
                try:
                    result = safe_json_parse(content, context="SpeakerMappingService LLM response")
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error(f"❌ Не удалось распарсить JSON ответа от LLM для маппинга спикеров: {e}")
                    raise SpeakerMappingLLMError(f"JSON parse failed: {e}") from e
```

Then the generic outer handler currently swallows API/schema errors:

```python
        except Exception as e:
            logger.error(f"Ошибка при вызове LLM для сопоставления: {e}")
            return {}
```

Replace it so a `SpeakerMappingLLMError` propagates unchanged and any other error is wrapped:

```python
        except SpeakerMappingLLMError:
            raise
        except Exception as e:
            logger.error(f"Ошибка при вызове LLM для сопоставления: {e}")
            raise SpeakerMappingLLMError(str(e)) from e
```

Leave the non-openai `else: return {}` branch (~line 594-598) untouched — that is a deliberate "not optimized for this provider" skip, not a failure.

- [ ] **Step 5: Add the dedicated handler in `map_speakers_to_participants`**

The method currently ends with a single generic handler:

```python
        except Exception as e:
            logger.error(f"Ошибка при сопоставлении спикеров: {e}")
            # Возвращаем пустой mapping и general тип
            return {}, "general"
```

Insert a dedicated branch BEFORE the generic one (order matters — the specific except must come first):

```python
        except SpeakerMappingLLMError as e:
            logger.error(
                f"SPEAKER_MAPPING_LLM_FAILED provider={llm_provider}: {e}. "
                "Протокол будет сгенерирован без сопоставления спикеров."
            )
            return {}, "general"
        except Exception as e:
            logger.error(f"Ошибка при сопоставлении спикеров: {e}")
            # Возвращаем пустой mapping и general тип
            return {}, "general"
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_speaker_mapping_failure.py -v`
Expected: both tests PASS — the hard failure path logs `SPEAKER_MAPPING_LLM_FAILED` and returns `({}, "general")`; the empty-but-successful path returns `({}, "business")` with no marker.

- [ ] **Step 7: Commit**

```bash
git add src/services/speaker_mapping_service.py tests/test_speaker_mapping_failure.py
git commit -m "fix(mapping): fail loudly on LLM mapping error instead of silent {}

A hard LLM/API/parse error in _call_llm_for_mapping used to return {} and be
indistinguishable from 'no confident matches', so a provider/schema break
disabled the speaker-mapping feature invisibly. Introduce SpeakerMappingLLMError,
raise it from both swallow points, and log a greppable SPEAKER_MAPPING_LLM_FAILED
marker in map_speakers_to_participants before degrading gracefully."
```

---

## Task 3: Verification gate (full suite + lint + schema sanity)

**Files:** none modified — this task only runs checks.

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS, including the pre-existing suite plus the new schema and failure tests. No regressions.

- [ ] **Step 2: Run the linter**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: clean (no errors). If `ruff format --check` reports the new files need formatting, run `.venv/bin/ruff format src/models/llm_schemas.py src/services/speaker_mapping_service.py tests/test_llm_schemas_strict.py tests/test_speaker_mapping_failure.py` and re-run the check.

- [ ] **Step 3: Local schema sanity check**

Run:
```bash
.venv/bin/python -c "
from src.models.llm_schemas import SPEAKER_MAPPING_SCHEMA, PROTOCOL_SCHEMA, MEETING_ANALYSIS_SCHEMA
for n, s in [('SPEAKER_MAPPING_SCHEMA', SPEAKER_MAPPING_SCHEMA), ('PROTOCOL_SCHEMA', PROTOCOL_SCHEMA), ('MEETING_ANALYSIS_SCHEMA', MEETING_ANALYSIS_SCHEMA)]:
    print(n, 'root additionalProperties =', s['schema'].get('additionalProperties'), '| strict =', s['strict'])
"
```
Expected output:
```
SPEAKER_MAPPING_SCHEMA root additionalProperties = False | strict = True
PROTOCOL_SCHEMA root additionalProperties = False | strict = True
MEETING_ANALYSIS_SCHEMA root additionalProperties = False | strict = True
```

- [ ] **Step 4: Commit (only if Step 2 reformatted files)**

If `ruff format` changed any file in Step 2, commit it:
```bash
git add -A
git commit -m "chore: ruff format for speaker-mapping schema fix"
```
Otherwise skip — no commit needed.

---

## Deployment (separate — requires explicit user confirmation)

This is an outward-facing, hard-to-reverse action. Do NOT run it as part of plan execution; confirm with the user first.

1. Merge the branch `fix/speaker-mapping-strict-schema` into `main` (PR or fast-forward, per the user's preference).
2. On prod (`jimmy@37.46.16.109`, project at `/home/jimmy/Soroka`):
   ```bash
   cd /home/jimmy/Soroka && git pull && sudo systemctl restart soroka.service
   ```
3. Verify: process a real meeting file that has diarization + a participants list. Expect in `journalctl -u soroka.service`:
   - the branch log "UI подтверждения сопоставления включён …",
   - the **confirmation message with buttons** delivered to the user,
   - no `400 Invalid schema ... SpeakerMappingSchema` errors.

---

## Self-Review

**1. Spec coverage:**
- Part 1 (schema `extra=forbid`) → Task 1, Step 3. ✅
- Part 2 (`get_json_schema` enforcement) → Task 1, Step 4. ✅
- Part 3 (typed exception + loud marker + graceful degrade) → Task 2, Steps 3-5. ✅
- Spec test #1 (root closed + strict) → Task 1, `test_speaker_mapping_schema_root_is_closed`. ✅
- Spec test #2 (parametrized guard over all schemas) → Task 1, `test_all_strict_schema_roots_are_closed`. ✅
- Spec test #3 (Dict fields keep typed additionalProperties) → Task 1, `test_dict_fields_keep_typed_additional_properties`. ✅
- Spec test #4 (failure logs marker, returns ({}, "general")) → Task 2, `test_mapping_llm_failure_is_loud_and_degrades` (+ negative test for empty-but-successful). ✅
- Verification (local schema regen, ruff, suite) → Task 3. ✅
- Optional metric → intentionally OUT (YAGNI): the greppable `SPEAKER_MAPPING_LLM_FAILED` ERROR marker provides the visibility; no metrics infra change. Documented here so the omission is deliberate, not a gap.

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to" placeholders. Every code step shows complete code and exact commands.

**3. Type/name consistency:** `SpeakerMappingLLMError` is defined in Task 2 Step 3 and referenced consistently in Steps 4-5 and both tests. `enforce_additional_properties_false` defined and called in Task 1 Step 4. The marker string is exactly `SPEAKER_MAPPING_LLM_FAILED` in both the implementation (Task 2 Step 5) and the assertion (Task 2 Step 1). Schema constant names match `src/models/llm_schemas.py:271-278`.
