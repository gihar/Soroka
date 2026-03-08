# Prompt Format Conventions

## Language
- All user-facing prompts MUST be in Russian
- Variable names and code identifiers in English

## FIELD_SPECIFIC_RULES format
- Emoji header: `📌 Название (english_name):`
- Required sections: НАЗНАЧЕНИЕ, ЧТО ИЗВЛЕКАТЬ, ФОРМАТ, ПРИМЕРЫ
- Examples use: `✅ ПРАВИЛЬНО:` / `❌ НЕПРАВИЛЬНО:`
- Bullet lists use `*` inside sections, `-` for top-level
- Max 10-15 lines for educational fields, 20 for core fields

## Context injection
- Guard with `if meeting_agenda or project_list:`
- Header: `## ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ДЛЯ АНАЛИЗА`
- Sub-headers: `**Повестка встречи:**`, `**Список проектов:**`

## Provider consistency
- All providers must pass the same context parameters
- Use `kwargs.get('param_name')` pattern — never direct access
- Context sections use identical formatting across all providers
