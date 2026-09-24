"""Repository for the company cache and each user's saved-companies list."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meridian.core.ids import utcnow
from meridian.db.models import CompanyModel, SavedCompanyModel, UserModel
from meridian.schemas.api import SavedCompany
from meridian.schemas.research import CompanyIdentity


def _company_from_row(row: CompanyModel) -> CompanyIdentity:
    return CompanyIdentity(
        name=row.name,
        ticker=row.ticker,
        cik=row.cik,
        exchange=row.exchange,
        sic=row.sic,
        sic_description=row.sic_description,
        fiscal_year_end=row.fiscal_year_end,
        state_of_incorporation=row.state_of_incorporation,
        website=row.website,
    )


class CompanyRepository:
    """Persists resolved companies and per-user saved-company lists.

    Takes an `AsyncSession` owned by the caller; never commits or opens its own transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, company: CompanyIdentity) -> None:
        values = {
            "ticker": company.ticker,
            "cik": company.cik,
            "name": company.name,
            "exchange": company.exchange,
            "sic": company.sic,
            "sic_description": company.sic_description,
            "fiscal_year_end": company.fiscal_year_end,
            "state_of_incorporation": company.state_of_incorporation,
            "website": company.website,
        }
        stmt = pg_insert(CompanyModel).values(**values)
        update_cols: dict[str, Any] = {c: stmt.excluded[c] for c in values if c != "ticker"}
        update_cols["updated_at"] = utcnow()
        stmt = stmt.on_conflict_do_update(index_elements=[CompanyModel.ticker], set_=update_cols)
        await self._session.execute(stmt)

    async def save_for_user(self, user_id: str, company: CompanyIdentity, research_id: str | None = None) -> None:
        await self._session.execute(
            pg_insert(UserModel).values(id=user_id).on_conflict_do_nothing(index_elements=[UserModel.id])
        )
        await self.upsert(company)
        stmt = pg_insert(SavedCompanyModel).values(user_id=user_id, ticker=company.ticker, last_research_id=research_id)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SavedCompanyModel.user_id, SavedCompanyModel.ticker],
            set_={"last_research_id": stmt.excluded.last_research_id},
        )
        await self._session.execute(stmt)

    async def remove_for_user(self, user_id: str, ticker: str) -> None:
        row = await self._session.get(SavedCompanyModel, {"user_id": user_id, "ticker": ticker.upper()})
        if row is not None:
            await self._session.delete(row)

    async def list_saved(self, user_id: str) -> list[SavedCompany]:
        stmt = (
            select(SavedCompanyModel, CompanyModel)
            .join(CompanyModel, CompanyModel.ticker == SavedCompanyModel.ticker)
            .where(SavedCompanyModel.user_id == user_id)
            .order_by(SavedCompanyModel.saved_at.desc())
        )
        result = await self._session.execute(stmt)
        return [
            SavedCompany(
                company=_company_from_row(company_row),
                saved_at=saved_row.saved_at,
                last_research_id=saved_row.last_research_id,
            )
            for saved_row, company_row in result.all()
        ]
