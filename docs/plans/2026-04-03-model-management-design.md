# Model Management — Design

## Goal

Allow admins to add, remove, and configure any OpenAI-compatible model (including OpenRouter) from the Telegram bot interface, with per-preset API keys and access control.

## Data Model

New table `model_presets` in SQLite:

| Field | Type | Description |
|-------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `key` | TEXT UNIQUE | Slug generated from model_id |
| `name` | TEXT | Display name |
| `model` | TEXT | Model ID for API |
| `base_url` | TEXT | API endpoint URL |
| `api_key` | TEXT NULL | Optional per-preset key (NULL = global) |
| `admin_only` | BOOLEAN DEFAULT FALSE | Restrict to admins |
| `is_enabled` | BOOLEAN DEFAULT TRUE | Enabled/disabled |
| `created_at` | TIMESTAMP | Creation date |

On startup, presets from `.env` (`OPENAI_MODELS`) are synced into DB via upsert on `key`.

## Admin Interface

### Quick add via command

```
/add_model google/gemini-2.0-flash "Gemini Flash" https://openrouter.ai/api/v1
```

Format: `/add_model <model_id> "<name>" <base_url> [api_key]`

`key` auto-generated from model_id (e.g. `google_gemini-2_0-flash`).

### Management via `/models`

List view with inline buttons. Tap a model to see detail card with actions:
- Edit name, URL, API key (step-by-step dialog)
- Toggle access (all users / admin only)
- Enable/disable
- Delete

### Sync button

"Sync from .env" re-imports `OPENAI_MODELS` presets into DB.

## OpenAIProvider Changes

Client cache by `(base_url, api_key)` tuple:
- `_get_client(preset)` returns cached or new `openai.OpenAI` instance
- `generate_protocol()` resolves preset, uses `_get_client(preset)` instead of `self.client`
- Global client remains default fallback

## Access Control

`model_preset_repo.get_available_for_user(user_id)`:
- `is_enabled=False` → hidden from everyone (visible in admin `/models`)
- `admin_only=True` → visible only to admins
- Otherwise → visible to all

Settings UI (`settings_callbacks.py`) uses this method for filtering.

## Backward Compatibility

- Existing `OPENAI_MODELS` env var continues to work
- Legacy `OPENAI_MODEL` + `OPENAI_BASE_URL` auto-creates a default preset
- User's `preferred_openai_model_key` works unchanged
- If preset is deleted and user still references it, falls back to default
