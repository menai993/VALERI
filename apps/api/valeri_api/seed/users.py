"""Dev/test application users (M8, D4).

One owner, one admin, one finance login + one login per seeded sales rep, all
sharing a documented dev password. Production users are created by an admin via
/settings/users; rotating away from the dev password is a pilot/runbook step (M14).
"""

from valeri_api.auth.passwords import hash_password

DEV_PASSWORD = "valeri-dev-2026"

OWNER_EMAIL = "vlasnik@ultrahigijena.ba"
ADMIN_EMAIL = "admin@ultrahigijena.ba"
FINANCE_EMAIL = "finansije@ultrahigijena.ba"


def generate_users(sales_reps: list[dict]) -> list[dict]:
    """Fixed role users + one sales_rep login per seeded rep."""
    # All dev users share the dev password — hash once (bcrypt is intentionally slow).
    password_hash = hash_password(DEV_PASSWORD)

    def user(
        user_id: int, name: str, email: str, role: str, sales_rep_id: int | None = None
    ) -> dict:
        return {
            "id": user_id,
            "name": name,
            "email": email,
            "role": role,
            "password_hash": password_hash,
            "sales_rep_id": sales_rep_id,
            "preferred_language": "bs",
        }

    users = [
        user(1, "Vlasnik", OWNER_EMAIL, "owner"),
        user(2, "Administrator", ADMIN_EMAIL, "admin"),
        user(3, "Finansije", FINANCE_EMAIL, "finance"),
    ]
    users.extend(
        user(4 + index, rep["name"], rep["email"], "sales_rep", sales_rep_id=rep["id"])
        for index, rep in enumerate(sales_reps)
    )
    return users
