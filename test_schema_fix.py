#!/usr/bin/env python3
"""
Тест для проверки исправлений схем JSON
"""

from src.models.llm_schemas import get_schema_by_type

def test_protocol_schema():
    """Проверяем ProtocolSchema на соответствие требованиям Azure OpenAI"""
    print("=== Testing ProtocolSchema ===")
    schema = get_schema_by_type('protocol')

    print(f"Schema name: {schema['name']}")
    print(f"Strict mode: {schema['strict']}")

    properties = schema['schema'].get('properties', {})
    required = schema['schema'].get('required', [])

    print(f"Properties count: {len(properties)}")
    print(f"Required fields: {len(required)}")

    # Проверяем, что все поля (кроме Dict) в required
    non_dict_fields = []
    dict_fields = []

    for prop_name, prop_schema in properties.items():
        if 'additionalProperties' in prop_schema:
            dict_fields.append(prop_name)
        else:
            non_dict_fields.append(prop_name)

    print(f"Non-Dict fields: {len(non_dict_fields)}")
    print(f"Dict fields: {len(dict_fields)}")

    missing_required = set(non_dict_fields) - set(required)
    extra_required = set(required) - set(non_dict_fields)

    if missing_required:
        print(f"❌ Missing required fields: {missing_required}")
    else:
        print("✅ All non-Dict fields are in required")

    if extra_required:
        print(f"⚠️  Extra required fields: {extra_required}")

    print()

def test_consolidated_schemas():
    """Проверяем консолидированные схемы"""
    print("=== Testing ConsolidatedExtractionSchema ===")
    schema = get_schema_by_type('consolidated_extraction')

    properties = schema['schema'].get('properties', {})
    required = schema['schema'].get('required', [])

    print(f"Properties count: {len(properties)}")
    print(f"Required fields: {len(required)}")

    # Проверяем, что все поля (кроме Dict) в required
    non_dict_fields = []
    dict_fields = []

    for prop_name, prop_schema in properties.items():
        if 'additionalProperties' in prop_schema:
            dict_fields.append(prop_name)
        else:
            non_dict_fields.append(prop_name)

    missing_required = set(non_dict_fields) - set(required)
    if missing_required:
        print(f"❌ Missing required fields: {missing_required}")
    else:
        print("✅ All non-Dict fields are in required")

    print()

    print("=== Testing ConsolidatedProtocolSchema ===")
    schema = get_schema_by_type('consolidated_protocol')

    properties = schema['schema'].get('properties', {})
    required = schema['schema'].get('required', [])

    print(f"Properties count: {len(properties)}")
    print(f"Required fields: {len(required)}")

    # Проверяем, что все поля (кроме Dict) в required
    non_dict_fields = []
    dict_fields = []

    for prop_name, prop_schema in properties.items():
        if 'additionalProperties' in prop_schema:
            dict_fields.append(prop_name)
        else:
            non_dict_fields.append(prop_name)

    missing_required = set(non_dict_fields) - set(required)
    if missing_required:
        print(f"❌ Missing required fields: {missing_required}")
    else:
        print("✅ All non-Dict fields are in required")

if __name__ == "__main__":
    test_protocol_schema()
    test_consolidated_schemas()
    print("Schema validation completed!")