"""Validators for LLM output: schema validation + the number contract.

The number contract is the mechanical guarantee behind principle 1: every
numeric token in a narration must exist in the masked payload's allowed set
(i.e. it is a SQL-computed value), otherwise the narration is rejected.
"""

import json
import re

from pydantic import ValidationError

from valeri_api.llm.masking import _normalise  # shared normalisation rules
from valeri_api.llm.schemas import TaskNarration


class NarrationInvalid(Exception):
    """The LLM response is not acceptable; carries the reasons for retry feedback."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
# Pseudonyms (Kupac-1f45a4) are identifiers, not numbers — their hex digits are
# excluded from the number contract.
_PSEUDONYM_PATTERN = re.compile(r"Kupac-[0-9a-fA-F]{6}")


def parse_narration(raw_text: str) -> TaskNarration:
    """Parse + schema-validate a raw LLM response. Raises NarrationInvalid."""
    match = _JSON_BLOCK.search(raw_text)
    if match is None:
        raise NarrationInvalid(["Odgovor ne sadrži JSON objekat."])

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise NarrationInvalid([f"Neispravan JSON: {error}"]) from error

    try:
        return TaskNarration.model_validate(data)
    except ValidationError as error:
        reasons = [
            f"Polje '{'.'.join(str(p) for p in issue['loc'])}': {issue['msg']}"
            for issue in error.errors()
        ]
        raise NarrationInvalid(reasons) from error


def extract_numbers(text: str) -> list[str]:
    """All numeric tokens in a text (both 12.5 and 12,5 forms); pseudonym digits excluded."""
    cleaned = _PSEUDONYM_PATTERN.sub("", text)
    return _NUMBER_PATTERN.findall(cleaned)


def check_number_contract(body: str, allowed_numbers: set[str]) -> list[str]:
    """Return the numeric tokens in the body that are NOT allowed (i.e. not from SQL)."""
    violations = []
    for token in extract_numbers(body):
        variants = _normalise(token)
        if not (variants & allowed_numbers):
            violations.append(token)
    return violations
