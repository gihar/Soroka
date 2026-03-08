# Gold Standard: LLM Provider context parameter passing
# All providers must pass meeting_agenda and project_list to prompt builders.
# Use kwargs.get() pattern with None defaults.

# Step 1: Extract from kwargs in generate_protocol()
# meeting_agenda = kwargs.get('meeting_agenda')
# project_list = kwargs.get('project_list')

# Step 2: Pass to prompt builder
# OpenAI/Anthropic use build_generation_prompt():
OPENAI_PATTERN = """
generation_user_prompt = build_generation_prompt(
    transcription=analysis_transcription,
    template_variables=template_variables,
    speaker_mapping=speaker_mapping,
    meeting_type=meeting_type,
    meeting_agenda=kwargs.get('meeting_agenda'),
    project_list=kwargs.get('project_list')
)
"""

# YandexGPT uses _build_user_prompt() with same params:
YANDEX_PATTERN = """
prompt = _build_user_prompt(
    transcription, template_variables, diarization_data,
    speaker_mapping, meeting_topic, meeting_date, meeting_time,
    participants, meeting_agenda, project_list
)
"""
