"""Legal entity, customer, contact, and sales-rep generation."""

import datetime
import random

from valeri_api.seed.config import SeedConfig
from valeri_api.seed.names import (
    FIRST_NAMES,
    HOTEL_GROUPS,
    HOTEL_OBJECTS,
    KAFIC_NAMES,
    KLINIKA_NAMES,
    LAST_NAMES,
    RESTORAN_NAMES,
    SALES_REP_NAMES,
    SKOLA_NAMES,
    STREETS,
)

_DIACRITICS = str.maketrans({c: r for c, r in zip("čćžšđČĆŽŠĐ", "cczsdCCZSD", strict=True)})


def _slug(name: str) -> str:
    """ASCII slug for synthetic e-mail domains."""
    cleaned = name.translate(_DIACRITICS).lower()
    return "".join(ch if ch.isalnum() else "-" for ch in cleaned).strip("-").replace("--", "-")


def generate_entities(rng: random.Random, config: SeedConfig) -> tuple[list[dict], list[dict]]:
    """Legal entities + customer objects.

    5 hotel groups with 2-3 objects each under ONE legal entity; every other
    customer is a standalone legal entity with exactly one object.
    """
    legal_entities: list[dict] = []
    customers: list[dict] = []
    entity_id = 0
    customer_id = 0

    def add_entity(name: str) -> int:
        nonlocal entity_id
        entity_id += 1
        legal_entities.append(
            {
                "id": entity_id,
                "name": name,
                "tax_id": f"4{200000000000 + entity_id}",  # synthetic JIB
            }
        )
        return entity_id

    def add_customer(entity: int, name: str, segment: str) -> int:
        nonlocal customer_id
        customer_id += 1
        customers.append(
            {
                "id": customer_id,
                "legal_entity_id": entity,
                "name": name,
                "segment": segment,
                "status": "active",
                "external_code": f"UH-{customer_id:04d}",
            }
        )
        return customer_id

    # Hotel groups: one legal entity, 2-3 objects.
    for group_name in HOTEL_GROUPS[: config.n_hotel_groups]:
        entity = add_entity(f"{group_name} d.o.o.")
        n_objects = rng.randint(2, 3)
        for object_name in rng.sample(HOTEL_OBJECTS, n_objects):
            add_customer(entity, f"{group_name} — {object_name}", "hotel")

    # Standalone customers: one legal entity each.
    standalone = [
        ("restoran", RESTORAN_NAMES, config.n_restoran, "{name} d.o.o."),
        ("kafić", KAFIC_NAMES, config.n_kafic, "{name} d.o.o."),
        ("klinika", KLINIKA_NAMES, config.n_klinika, "PZU {name}"),
        ("škola", SKOLA_NAMES, config.n_skola, "JU {name}"),
    ]
    for segment, names, count, entity_format in standalone:
        for name in names[:count]:
            entity = add_entity(entity_format.format(name=name))
            add_customer(entity, name, segment)

    return legal_entities, customers


def generate_contacts(rng: random.Random, customers: list[dict]) -> list[dict]:
    """1-2 synthetic contacts per customer (synthetic PII)."""
    contacts: list[dict] = []
    contact_id = 0

    for customer in customers:
        domain = _slug(customer["name"])[:30].strip("-")
        for _ in range(rng.randint(1, 2)):
            contact_id += 1
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            street = rng.choice(STREETS)
            contacts.append(
                {
                    "id": contact_id,
                    "customer_id": customer["id"],
                    "name": f"{first} {last}",
                    "email": f"{_slug(first)}.{_slug(last)}@{domain}.ba",
                    "phone": (
                        f"+387 6{rng.randint(0, 5)} "
                        f"{rng.randint(100, 999)} {rng.randint(100, 999)}"
                    ),
                    "address": f"{street} {rng.randint(1, 99)}, Sarajevo",
                }
            )

    return contacts


def generate_reps(
    rng: random.Random, config: SeedConfig, customers: list[dict], from_date: datetime.date
) -> tuple[list[dict], list[dict]]:
    """Sales reps + one assignment per customer (round-robin, stable)."""
    reps = [
        {
            "id": i + 1,
            "name": name,
            "email": f"{_slug(name)}@ultrahigijena.ba",
        }
        for i, name in enumerate(SALES_REP_NAMES[: config.n_reps])
    ]

    assignments = [
        {
            "customer_id": customer["id"],
            "sales_rep_id": reps[index % len(reps)]["id"],
            "from_date": from_date,
        }
        for index, customer in enumerate(customers)
    ]

    return reps, assignments
