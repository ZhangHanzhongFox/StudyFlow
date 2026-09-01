"""Prompts for assessment classification and task decomposition."""

from backend.schemas import Assessment

CLASSIFICATION_SYSTEM_PROMPT = """\
Classify one university assessment into the supplied assessment type schema.
Use only the title, description, and existing normalized type as evidence.
Do not invent missing assessment facts.
"""

DECOMPOSITION_SYSTEM_PROMPT = """\
Decompose one university assessment into actionable, independently schedulable
study tasks. Use concise snake_case step_key values, action-oriented names,
positive integer durations in minutes, and priorities from 1 to 5 where 5 is
most urgent. Dependencies may reference only step_key values in this response.
Do not schedule tasks or invent requirements absent from the assessment.
"""


def assessment_prompt(assessment: Assessment) -> str:
    """Serialize the validated assessment as the dynamic prompt payload."""

    return assessment.model_dump_json()
