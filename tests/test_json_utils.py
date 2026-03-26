"""Tests for LLM JSON parsing utilities."""
import importlib.util
import os
import pytest

# Import json_utils directly to avoid triggering src.llm.__init__
# which requires heavy runtime deps (openai, anthropic)
_spec = importlib.util.spec_from_file_location(
    "json_utils",
    os.path.join(os.path.dirname(__file__), "..", "src", "llm", "json_utils.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
safe_json_parse = _mod.safe_json_parse


def test_parse_valid_json():
    result = safe_json_parse('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_in_markdown_block():
    text = '```json\n{"key": "value"}\n```'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_json_with_surrounding_text():
    text = 'Here is the result: {"key": "value"} done.'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_json_with_trailing_comma():
    text = '{"key": "value",}'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_json_with_comments():
    text = '{"key": "value" // comment\n}'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_empty_string_raises():
    with pytest.raises((ValueError, Exception)):
        safe_json_parse("")


def test_parse_invalid_json_raises():
    with pytest.raises((ValueError, Exception)):
        safe_json_parse("not json at all")


def test_parse_with_bom():
    text = '\ufeff{"key": "value"}'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_nested_json():
    text = '{"outer": {"inner": "value"}, "list": [1, 2, 3]}'
    result = safe_json_parse(text)
    assert result["outer"]["inner"] == "value"
    assert result["list"] == [1, 2, 3]


def test_parse_json_array():
    text = '[{"id": 1}, {"id": 2}]'
    result = safe_json_parse(text)
    assert len(result) == 2
    assert result[0]["id"] == 1
