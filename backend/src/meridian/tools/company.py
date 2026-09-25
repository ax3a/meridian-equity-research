"""Company identity and profile tools: resolve_company, search_companies, get_company_profile."""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.providers.base import CompanyProfile
from meridian.schemas.research import CompanyIdentity
from meridian.tools.base import Tool, ToolContext


class ResolveCompanyInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ResolveCompanyOutput(BaseModel):
    company: CompanyIdentity
    evidence_ids: list[str] = Field(default_factory=list)


class ResolveCompanyTool(Tool[ResolveCompanyInput, ResolveCompanyOutput]):
    """Resolve a ticker or company name to a canonical `CompanyIdentity` (name, ticker, CIK)."""

    name = "resolve_company"
    description = "Resolve a ticker symbol or company name to a canonical company identity (name, ticker, CIK)."
    input_model = ResolveCompanyInput

    async def run(self, args: ResolveCompanyInput, ctx: ToolContext) -> ResolveCompanyOutput:
        identity = await ctx.providers.directory.resolve(args.query)
        # Ticker/name resolution itself is not a citable fact -- no evidence to carry.
        return ResolveCompanyOutput(company=identity, evidence_ids=[])

    def summarize(self, output: ResolveCompanyOutput) -> str:
        c = output.company
        return f"{c.name} ({c.ticker}), CIK {c.cik}"


class SearchCompaniesInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=8, ge=1, le=25)


class SearchCompaniesOutput(BaseModel):
    results: list[CompanyIdentity]


class SearchCompaniesTool(Tool[SearchCompaniesInput, SearchCompaniesOutput]):
    """Fuzzy company search by ticker prefix or name substring, for disambiguation/autocomplete."""

    name = "search_companies"
    description = "Search for companies by ticker prefix or name substring. Returns candidate matches."
    input_model = SearchCompaniesInput

    async def run(self, args: SearchCompaniesInput, ctx: ToolContext) -> SearchCompaniesOutput:
        results = await ctx.providers.directory.search(args.query, args.limit)
        return SearchCompaniesOutput(results=results)

    def summarize(self, output: SearchCompaniesOutput) -> str:
        return "; ".join(f"{c.ticker}:{c.name}" for c in output.results)[:6000]


class GetCompanyProfileInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)


class GetCompanyProfileOutput(BaseModel):
    profile: CompanyProfile
    evidence_ids: list[str]


class GetCompanyProfileTool(Tool[GetCompanyProfileInput, GetCompanyProfileOutput]):
    """Company profile: SIC/industry, exchange, fiscal year end, incorporation, description."""

    name = "get_company_profile"
    description = (
        "Fetch a company's SEC EDGAR entity profile: SIC industry code and description, exchange, "
        "fiscal year end, state of incorporation, and business description."
    )
    input_model = GetCompanyProfileInput

    async def run(self, args: GetCompanyProfileInput, ctx: ToolContext) -> GetCompanyProfileOutput:
        identity = await ctx.providers.directory.resolve(args.ticker)
        result = await ctx.providers.directory.profile(identity)
        ctx.ledger.absorb(result)
        return GetCompanyProfileOutput(profile=result.data, evidence_ids=[e.id for e in result.evidence])

    def summarize(self, output: GetCompanyProfileOutput) -> str:
        p = output.profile
        eid_str = f" [{output.evidence_ids[0]}]" if output.evidence_ids else ""
        return (
            f"{p.identity.name} ({p.identity.ticker}): SIC {p.identity.sic} ({p.identity.sic_description}), "
            f"exchange {p.identity.exchange}, fiscal year end {p.identity.fiscal_year_end}{eid_str}"
        )
