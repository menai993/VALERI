"""Articles API (M8): list/detail + the lost-articles view — per docs/api-spec.md.

All authenticated roles; reps see lost-article rows only for their own customers.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.auth.deps import CurrentUser, visible_customer_ids
from valeri_api.db import get_session
from valeri_api.metrics.dashboard import lost_article_rows
from valeri_api.metrics.schemas import LostArticleRow

router = APIRouter()


class ArticleRow(BaseModel):
    id: int
    code: str
    name: str
    active: bool
    category_id: int | None
    category_name: str | None


class ArticleListResponse(BaseModel):
    items: list[ArticleRow]
    next_cursor: int | None = None


class LostArticleListResponse(BaseModel):
    items: list[LostArticleRow]


_ARTICLE_SELECT = """
SELECT a.id, a.code, a.name, a.active, a.category_id, cat.name AS category_name
FROM core.article a
LEFT JOIN core.category cat ON cat.id = a.category_id
"""


@router.get("/articles", response_model=ArticleListResponse)
def list_articles(
    session: Annotated[Session, Depends(get_session)],
    _user: CurrentUser,
    query: str | None = None,
    category: int | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> ArticleListResponse:
    """List/search the article catalog."""
    limit = max(1, min(limit, 200))
    rows = session.execute(
        text(_ARTICLE_SELECT + """
            WHERE (CAST(:query AS text) IS NULL
                   OR a.name ILIKE '%' || :query || '%' OR a.code ILIKE '%' || :query || '%')
              AND (CAST(:category AS bigint) IS NULL OR a.category_id = :category)
              AND (CAST(:cursor AS bigint) IS NULL OR a.id > :cursor)
            ORDER BY a.id
            LIMIT :limit_plus_one
            """),
        {"query": query, "category": category, "cursor": cursor, "limit_plus_one": limit + 1},
    ).mappings()

    items = [ArticleRow(**dict(row)) for row in rows]
    has_more = len(items) > limit
    items = items[:limit]
    return ArticleListResponse(
        items=items, next_cursor=items[-1].id if has_more and items else None
    )


@router.get("/articles/lost", response_model=LostArticleListResponse)
def list_lost_articles(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
    customer_id: int | None = None,
    limit: int = 50,
) -> LostArticleListResponse:
    """The lost-article view (MVP centerpiece): per-customer lost articles + evidence."""
    scope = visible_customer_ids(user, session)
    return LostArticleListResponse(
        items=lost_article_rows(
            session, limit=max(1, min(limit, 200)), customer_id=customer_id, customer_ids=scope
        )
    )


@router.get("/articles/{article_id}", response_model=ArticleRow)
def get_article(
    article_id: int,
    session: Annotated[Session, Depends(get_session)],
    _user: CurrentUser,
) -> ArticleRow:
    """Article detail."""
    row = (
        session.execute(text(_ARTICLE_SELECT + " WHERE a.id = :id"), {"id": article_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Article {article_id} not found"},
        )
    return ArticleRow(**jsonable(dict(row)))
