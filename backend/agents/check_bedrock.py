"""Run with python -m backend.agents.check_bedrock in a credentialed shell."""

from botocore.exceptions import ClientError

from backend.schemas import AssessmentType
from backend.services.mock_data import MockDataStore

from .bedrock import configured_llm
from .llm import DecompositionOutput
from .prompts import DECOMPOSITION_SYSTEM_PROMPT, assessment_prompt


def main() -> int:
    """Make one structured request, with no template fallback hiding failures."""

    try:
        llm = configured_llm()
        if llm is None:
            print("Set STUDYFLOW_LLM_PROVIDER=bedrock before running this check.")
            return 1
        assessment = next(
            item for item in MockDataStore().list_assessments()
            if item.type is AssessmentType.PRESENTATION
        )
        output = llm.generate(
            system_prompt=DECOMPOSITION_SYSTEM_PROMPT,
            user_prompt=assessment_prompt(assessment),
            response_model=DecompositionOutput,
        )
    except Exception as error:
        # Do not print SDK exceptions or request bodies containing private data.
        print(f"Bedrock structured check failed: {type(error).__name__}")
        if isinstance(error, ClientError):
            print("AWS error code:", error.response["Error"]["Code"])
        print("Check SDK installation, current AWS credentials, region and model access.")
        return 1
    print("Bedrock structured output OK (Pydantic validated; no template fallback).")
    print(output.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
