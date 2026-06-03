"""CI1 extraction contract (bug fix): the canonical deal validates on the FIRST
try — including the same_owner relationship — so capture stays on Haiku and never
cascades. Pins the exact output shape the (now explicit) prompt asks for.
"""

import json

import pytest

from valeri_api.kb.schemas import ExtractionResult
from valeri_api.llm.validators import NarrationInvalid, parse_structured

# The canonical capture (the live-repro deal), shaped exactly as the prompt asks.
_CANONICAL = json.dumps(
    {
        "facts": [
            {
                "fact_type": "intent",
                "fact_key": "category_expansion",
                "value": {"kategorija": "hemija"},
                "mentioned_name": "Hotel Aria",
                "source": "stated",
                "stakes": "low",
                "confidence": 0.9,
                "evidence_span": "kreću i s hemijom",
            }
        ],
        "events": [
            {
                "kind": "deal",
                "summary": "Godišnji ugovor",
                "mentioned_name": "Hotel Aria",
                "value": 72000,
                "categories": ["hemija"],
                "occurred_on": None,
                "source": "stated",
                "confidence": 0.95,
                "evidence_span": "Zaključio sam godišnji ugovor s Hotel Aria, 72000 KM",
            }
        ],
        "relationships": [
            {
                "rel_type": "same_owner",
                "from_name": "Hotel Aria",
                "to_name": "Hotel Panorama",
                "source": "stated",
                "confidence": 0.85,
                "evidence_span": "isti vlasnik kao Hotel Panorama",
            }
        ],
        "confidence": 0.9,
    }
)


def test_canonical_deal_validates_first_try() -> None:
    result = parse_structured(_CANONICAL, ExtractionResult)
    # The deal value is a plain number, stored as data.
    assert len(result.events) == 1
    assert float(result.events[0].value) == 72000.0
    assert result.events[0].kind == "deal"
    # The fact value is a dict.
    assert isinstance(result.facts[0].value, dict)
    # The same_owner relationship — the CI centerpiece — is NOT dropped.
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.rel_type == "same_owner"
    assert rel.from_name == "Hotel Aria"
    assert rel.to_name == "Hotel Panorama"


def test_fact_value_scalar_is_coerced_not_rejected() -> None:
    """A fact whose value the model emits as a scalar is wrapped, not rejected."""
    payload = json.dumps(
        {
            "facts": [
                {
                    "fact_type": "payment_late",
                    "fact_key": "status",
                    "value": "kasni",  # scalar, not a dict
                    "source": "stated",
                    "confidence": 0.86,
                    "evidence_span": "kasni s plaćanjem",
                }
            ],
            "events": [],
            "relationships": [],
            "confidence": 0.86,
        }
    )
    result = parse_structured(payload, ExtractionResult)
    assert result.facts[0].value == {"value": "kasni"}  # coerced into a dict


def test_event_value_currency_string_is_rejected() -> None:
    """An event value with currency/thousands formatting is rejected — the prompt
    must produce a plain number (this documents why the prompt is explicit)."""
    payload = json.dumps(
        {
            "facts": [],
            "events": [
                {
                    "kind": "deal",
                    "summary": "Ugovor",
                    "value": "72.000 KM",  # currency string — not a number
                    "source": "stated",
                    "confidence": 0.9,
                    "evidence_span": "72.000 KM",
                }
            ],
            "relationships": [],
            "confidence": 0.9,
        }
    )
    with pytest.raises(NarrationInvalid):
        parse_structured(payload, ExtractionResult)
