# Gold Standard: FIELD_SPECIFIC_RULES entry
# Each entry in the FIELD_SPECIFIC_RULES dict follows this structure:
# - Emoji header with field name in Russian and English
# - НАЗНАЧЕНИЕ: purpose of the field
# - ЧТО ИЗВЛЕКАТЬ: what to extract (bullet list with *)
# - ЧТО ИГНОРИРОВАТЬ: what to skip
# - ФОРМАТ: output format description
# - ПРИМЕРЫ: examples with ✅ ПРАВИЛЬНО / ❌ НЕПРАВИЛЬНО
# - ОСОБЫЕ СЛУЧАИ: edge cases
# Keep entries to 10-15 lines for educational fields, up to 20 for core fields.

EXAMPLE = """📌 Решения (decisions):
- НАЗНАЧЕНИЕ: Согласованные, утвержденные решения, принятые на встрече
- ЧТО ИЗВЛЕКАТЬ:
  * Только решения, которые были ПРИНЯТЫ и СОГЛАСОВАНЫ участниками
  * Четко формулируй уровень определенности
- ЧТО ИГНОРИРОВАТЬ:
  * Предложения, которые не были приняты
  * Общие обсуждения без финального решения
- ФОРМАТ: Многострочный текст с маркерами "- " для каждого решения
- ПРИМЕРЫ:
  ✅ ПРАВИЛЬНО: "- Принято решение использовать микросервисную архитектуру..."
  ❌ НЕПРАВИЛЬНО: "Обсудили архитектуру" (не решение)
- ОСОБЫЕ СЛУЧАИ:
  * Если решений не было: "Решения не были приняты на данной встрече"
  * Условные решения: отмечай условия"""
