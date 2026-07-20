"""Deprecated-стаб форматирования удалён.

`_get_type_specific_formatting_instructions` возвращал "" и нигде не вызывался
(живой путь — `_get_type_specific_instructions`).
"""


def test_deprecated_formatting_stub_removed():
    import src.prompts.prompts as prompts

    assert not hasattr(prompts, "_get_type_specific_formatting_instructions")


def test_live_instructions_function_present():
    import src.prompts.prompts as prompts

    assert hasattr(prompts, "_get_type_specific_instructions")
