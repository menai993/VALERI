"""FastAPI dependencies for authentication + RBAC (M8).

Every protected endpoint declares either current_user (any authenticated user)
or require_roles(...) (specific roles). Sales reps additionally get row-level
scoping through visible_customer_ids() — a rep only ever sees customers
currently assigned to them in core.customer_rep.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.auth.models import AppUser
from valeri_api.auth.tokens import COOKIE_NAME, TokenInvalid, decode_token
from valeri_api.db import get_session


def _unauthorized(message: str = "Prijava je obavezna") -> HTTPException:
    return HTTPException(status_code=401, detail={"code": "unauthorized", "message": message})


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "forbidden", "message": "Nemate pristup ovom sadržaju"},
    )


def current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> AppUser:
    """The logged-in user, resolved from the session cookie. 401 otherwise."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise _unauthorized()
    try:
        payload = decode_token(raw)
    except TokenInvalid as error:
        raise _unauthorized("Sesija je istekla ili je nevažeća") from error

    user = session.get(AppUser, int(payload["sub"]))
    if user is None:
        raise _unauthorized("Korisnik više ne postoji")
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]


def require_roles(*roles: str):
    """Dependency factory: the current user must hold one of the given roles (403 otherwise)."""

    def checker(user: CurrentUser) -> AppUser:
        if user.role not in roles:
            raise _forbidden()
        return user

    return checker


# The current rep assignment per customer (latest from_date wins).
_REP_CUSTOMERS_SQL = """
SELECT customer_id FROM (
    SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id
    FROM core.customer_rep
    ORDER BY customer_id, from_date DESC
) current_assignment
WHERE sales_rep_id = :sales_rep_id
"""


def visible_customer_ids(user: AppUser, session: Session) -> set[int] | None:
    """Row-level scope: None = all customers (owner/admin/finance); a set for reps.

    A rep login without a linked sales_rep row sees nothing (empty set), never
    everything — fail closed.
    """
    if user.role != "sales_rep":
        return None
    if user.sales_rep_id is None:
        return set()
    rows = session.execute(text(_REP_CUSTOMERS_SQL), {"sales_rep_id": user.sales_rep_id})
    return {row[0] for row in rows}
