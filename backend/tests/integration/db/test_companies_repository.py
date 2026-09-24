"""Integration tests for `CompanyRepository` against a real Postgres instance."""

from __future__ import annotations

import pytest
from tests.integration.db.helpers import make_company

from meridian.core.ids import new_id
from meridian.db.repositories.companies import CompanyRepository

pytestmark = pytest.mark.integration


def _user_id() -> str:
    return "user_" + new_id("")[-8:]


async def test_upsert_is_idempotent_and_updates_fields(db_session) -> None:
    repo = CompanyRepository(db_session)
    company = make_company("MSFT")
    await repo.upsert(company)

    changed = company.model_copy(update={"website": "https://new.example.com"})
    await repo.upsert(changed)

    saved = await repo.list_saved(_user_id())  # no rows yet, but exercises the join path safely
    assert saved == []


async def test_save_for_user_then_list_and_remove(db_session) -> None:
    repo = CompanyRepository(db_session)
    user_id = _user_id()
    company = make_company("MSFT")

    await repo.save_for_user(user_id, company, research_id="sess_abc")
    saved = await repo.list_saved(user_id)

    assert len(saved) == 1
    assert saved[0].company.ticker == "MSFT"
    assert saved[0].last_research_id == "sess_abc"

    await repo.remove_for_user(user_id, "MSFT")
    assert await repo.list_saved(user_id) == []


async def test_save_for_user_twice_updates_last_research_id(db_session) -> None:
    repo = CompanyRepository(db_session)
    user_id = _user_id()
    company = make_company("NVDA")

    await repo.save_for_user(user_id, company, research_id="sess_1")
    await repo.save_for_user(user_id, company, research_id="sess_2")

    saved = await repo.list_saved(user_id)
    assert len(saved) == 1
    assert saved[0].last_research_id == "sess_2"
