# Template Consolidation Design

**Date:** 2026-03-29
**Status:** Approved
**Goal:** Reduce 27 templates to 7, remove categories, flatten UI

## Context

27 templates in the system. 16 (59%) have zero usage. Out of 194 total processings,
86 (44%) use "Стандартный протокол". Categories add navigation overhead for 7 items.

## Final Template Set (7)

| # | Name | Old IDs | Usage |
|---|------|---------|-------|
| 1 | Стандартный протокол встречи | 1 | 86 |
| 2 | Краткое резюме встречи | 2 | 8 |
| 3 | Техническое совещание | 3 | 18 |
| 4 | Daily Standup | 17 | 8 |
| 5 | Протокол поручений | 22+31 | 9 |
| 6 | Sprint Retrospective | 15 | 0 (unique format) |
| 7 | Лекция и презентация | 23 | 0 (future use) |

## Templates to Delete (20)

- General dups: #7, #20, #21
- Management (0 usage): #8, #9, #10, #11, #12, #13
- Product (0 usage): #14, #16, #18, #19
- Business: #29
- Educational: #24, #25, #26, #27, #28

## Changes

### 1. template_library.py
- Remove `CATEGORIES` dict
- Remove `get_management_templates()`, `get_product_templates()`, `get_educational_templates()`
- Replace with single `get_all_templates()` returning flat list of 7 templates
- Remove `category` field from template dicts (set to None or omit)

### 2. Database cleanup
- Delete removed templates from `templates` table
- Reset `default_template_id` to NULL for users pointing to deleted templates
- Keep `category` column in schema (backward compat) but stop using it

### 3. UI changes (callback_handlers, template_handlers)
- Remove category selection step — show flat list of 7 templates directly
- Remove `select_category_*`, `view_template_category_*`, `template_category_*` callbacks
- Simplify `quick_actions.py` template selection

### 4. Smart selector
- Update `smart_template_selector.py` to work with 7 templates
- Re-index on startup (already happens automatically)

## Data Migration

```sql
-- Users with default_template pointing to deleted templates -> reset to smart selection
UPDATE users SET default_template_id = NULL
WHERE default_template_id IN (7,8,9,10,11,12,13,14,16,18,19,20,21,24,25,26,27,28,29);

-- Merge OD templates: keep 22, delete 31
-- (processing_history references stay — historical data)
UPDATE processing_history SET template_id = 22 WHERE template_id = 31;
DELETE FROM templates WHERE id = 31;

-- Delete unused templates
DELETE FROM templates WHERE id IN (7,8,9,10,11,12,13,14,16,18,19,20,24,25,26,27,28,29);

-- Clear category on remaining templates
UPDATE templates SET category = NULL;
```

## Verification

1. Bot starts, `/start` command works
2. Template selection shows flat list of 7 items
3. Smart selection still works (re-indexes automatically)
4. Existing user defaults not broken (reset to smart if deleted)
5. Processing with each remaining template produces valid output
