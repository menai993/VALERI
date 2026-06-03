"""Server-side entity resolution (M9, spec D4): deterministic, never the model.

Customer names mentioned in a chat message are found by normalised substring
matching against core.customer (~80 rows — an exhaustive scan is fine). The
model only ever sees pseudonyms; mapping back to ids happens here.

Fuzzy matching (pg_trgm), aliases and clarification questions belong to CI1.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

# Bosnian diacritics → ASCII for match normalisation (đ→dj is the common convention).
_DIACRITICS = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d"})


def normalise(value: str) -> str:
    """Lowercase + diacritic-free form used for matching (never stored)."""
    return value.lower().translate(_DIACRITICS)


def resolve_entities(session: Session, message_text: str) -> list[tuple[str, int, str]]:
    """Find customer names mentioned in the text.

    Returns [(matched_text_as_it_appears, customer_id, real_name)], longest names
    first so "Hotel Stari Grad — Objekat 2" wins over "Hotel Stari Grad".
    """
    normalised_message = normalise(message_text)

    customers = session.execute(text("SELECT id, name FROM core.customer ORDER BY id")).all()

    # Longest names first prevents a shorter name shadowing a longer match.
    by_length = sorted(customers, key=lambda row: len(row.name), reverse=True)

    resolved: list[tuple[str, int, str]] = []
    claimed: list[tuple[int, int]] = []  # (start, end) spans already matched

    for customer_id, name in ((row.id, row.name) for row in by_length):
        needle = normalise(name)
        start = normalised_message.find(needle)
        if start < 0:
            continue
        end = start + len(needle)
        # Skip if this span overlaps an already-claimed (longer) match.
        if any(start < c_end and end > c_start for c_start, c_end in claimed):
            continue
        claimed.append((start, end))
        # The matched text as it appears in the original message (same span).
        matched_text = message_text[start:end]
        resolved.append((matched_text, customer_id, name))

    return resolved
