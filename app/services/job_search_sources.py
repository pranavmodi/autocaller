"""Curated discovery sources for the Job Agent search profile.

The catalog is operator-visible configuration, not evidence that a job is live.
Every discovered role still goes through the existing employer/job verifier.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.services.quick_job_links import list_quick_job_links


class JobSearchSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    name: str
    url: HttpUrl
    method: Literal["public_api", "public_feed", "public_page", "web_search"]
    enabled_by_default: bool = False
    note: str
    aliases: list[str] = Field(default_factory=list)

    @property
    def available(self) -> bool:
        return True


# The user's 30-item list normalizes to 27 distinct sources. AngelList is now
# Wellfound; Remotees and Remote OK Europe were duplicated in the supplied list.
# Obvious link errors are corrected here rather than persisted as broken input.
SOURCE_CATALOG = (
    JobSearchSource(id="remotive", name="Remotive", url="https://remotive.com/api/remote-jobs",
                    method="public_api", enabled_by_default=True,
                    note="Free public JSON API; results are delayed and require Remotive attribution."),
    JobSearchSource(id="himalayas", name="Himalayas", url="https://himalayas.app/jobs/api",
                    method="public_api", enabled_by_default=True,
                    note="Free public JSON API with typed filters; credit and link back to Himalayas."),
    JobSearchSource(id="toptal", name="Toptal", url="https://www.toptal.com/talent/apply",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunities only; do not automate its account or screening flow."),
    JobSearchSource(id="turing", name="Turing", url="https://work.turing.com/",
                    method="web_search", enabled_by_default=True,
                    note="Search public role pages for global remote AI and software work; do not automate profile, assessment or login flows."),
    JobSearchSource(id="andela", name="Andela", url="https://www.andela.com/for-talent",
                    method="web_search", enabled_by_default=True,
                    note="Search public opportunity pages; most matching and applications require the Talent Cloud, which is not automated."),
    JobSearchSource(id="arc", name="Arc", url="https://arc.dev/remote-jobs/ai",
                    method="public_page", enabled_by_default=True,
                    note="Public remote AI job index with worldwide, country and employment-type information; verify each employer listing."),
    JobSearchSource(id="braintrust", name="Braintrust", url="https://www.usebraintrust.com/jobs",
                    method="public_page", enabled_by_default=True,
                    note="Public role categories and examples; job matching and certification inside an account are not automated."),
    JobSearchSource(id="g2i", name="G2i", url="https://jobs.ashbyhq.com/g2i",
                    method="web_search", enabled_by_default=True,
                    note="Search the public G2i Ashby board and indexed role pages; do not automate talent-account flows."),
    JobSearchSource(id="proxify", name="Proxify", url="https://career.proxify.io/",
                    method="web_search", enabled_by_default=True,
                    note="Search public career pages; members-only openings, vetting and account flows are not automated."),
    JobSearchSource(id="gunio", name="Gun.io", url="https://gun.io/find-work/",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunities; Gun.io primarily matches vetted profiles to roles and that account flow is not automated."),
    JobSearchSource(id="ateam", name="A.Team", url="https://www.a.team/join",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed AI and product missions; application, evaluation and account-only mission access are not automated."),
    JobSearchSource(id="contra", name="Contra", url="https://contra.com/opportunities",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed freelance opportunities; do not bypass account or paid-feature access."),
    JobSearchSource(id="crossover", name="Crossover", url="https://www.crossover.com/jobs",
                    method="public_page", enabled_by_default=True,
                    note="Public global remote job index; search listed roles but do not automate assessment or proctored screening stages."),
    JobSearchSource(id="wellfound", name="Wellfound", url="https://wellfound.com/jobs",
                    method="web_search", enabled_by_default=True,
                    note="Discover public job pages through web search; do not automate account-only flows.",
                    aliases=["AngelList"]),
    JobSearchSource(id="pangian", name="Pangian", url="https://pangian.com/",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed pages; the direct service may be unavailable."),
    JobSearchSource(id="remote_co", name="Remote.co", url="https://remote.co/remote-jobs/",
                    method="public_page", enabled_by_default=True,
                    note="Public remote-job categories and job pages."),
    JobSearchSource(id="remoteok", name="Remote OK", url="https://remoteok.com/api",
                    method="public_api", enabled_by_default=True,
                    note="Free public JSON feed; credit and link back to the source listing."),
    JobSearchSource(id="remotees", name="Remotees", url="https://remotees.co/",
                    method="public_page", enabled_by_default=True,
                    note="Public remote-job pages; corrected from the stale remotees.com link.",
                    aliases=["Remotees (duplicate entry)"]),
    JobSearchSource(id="flexjobs", name="FlexJobs", url="https://www.flexjobs.com/remote-jobs",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed job pages only; do not bypass subscription access."),
    JobSearchSource(id="linkedin", name="LinkedIn Jobs", url="https://www.linkedin.com/jobs/",
                    method="web_search", enabled_by_default=True,
                    note="Use indexed public job pages only; no logged-in scraping or account automation."),
    JobSearchSource(id="remote4me", name="Remote4Me", url="https://remote4me.com/remote-jobs",
                    method="public_page", enabled_by_default=True,
                    note="Public remote-job index."),
    JobSearchSource(id="jobspresso", name="Jobspresso", url="https://jobspresso.co/remote-work/",
                    method="public_page", enabled_by_default=True,
                    note="Public curated remote-job pages."),
    JobSearchSource(id="upwork", name="Upwork", url="https://www.upwork.com/freelance-jobs/",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunities only; do not automate account-only bidding."),
    JobSearchSource(id="freelancer", name="Freelancer", url="https://www.freelancer.com/jobs/",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunities only; do not automate account-only bidding."),
    JobSearchSource(id="outsourcely", name="Outsourcely", url="https://www.outsourcely.com/remote-workers",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunities only; do not automate account-only flows."),
    JobSearchSource(id="simplyhired", name="SimplyHired", url="https://www.simplyhired.com/search?q=remote",
                    method="web_search", enabled_by_default=True,
                    note="Use indexed public result/job pages and verify every role at the employer source."),
    JobSearchSource(id="remote_in_europe", name="Remote in Europe", url="https://remoteineurope.com/",
                    method="public_page", enabled_by_default=True,
                    note="Public Europe-focused remote-job board.", aliases=["Remote OK Europe"]),
    JobSearchSource(id="remotehabits", name="RemoteHabits", url="https://remotehabits.com/",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunity pages; this source may return no current roles."),
    JobSearchSource(id="nodesk", name="NoDesk", url="https://nodesk.co/remote-jobs/",
                    method="public_page", enabled_by_default=True,
                    note="Public curated remote-job pages."),
    JobSearchSource(id="skip_the_drive", name="SkipTheDrive", url="https://www.skipthedrive.com/",
                    method="public_page", enabled_by_default=True,
                    note="Public remote-job pages; corrected from the supplied skipthechive.com typo."),
    JobSearchSource(id="working_nomads", name="Working Nomads", url="https://www.workingnomads.com/remote-jobs",
                    method="public_page", enabled_by_default=True,
                    note="Public remote-job index."),
    JobSearchSource(id="europe_remotely", name="Europe Remotely", url="https://europeremotely.com/",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunity pages; verify every result at the employer source."),
    JobSearchSource(id="we_work_remotely", name="We Work Remotely", url="https://weworkremotely.com/remote-jobs.rss",
                    method="public_feed", enabled_by_default=True,
                    note="Public RSS feed; attribute and link back to the source listing."),
    JobSearchSource(id="remote_freelance", name="Remote Freelance", url="https://remotefreelance.com/",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunity pages; verify every result at the employer source."),
    JobSearchSource(id="stackoverflow_jobs", name="Stack Overflow Jobs", url="https://stackoverflow.jobs/",
                    method="web_search", enabled_by_default=True,
                    note="Public technology-job search powered by Indeed; verify at the employer source."),
    JobSearchSource(id="virtual_vocations", name="Virtual Vocations", url="https://www.virtualvocations.com/jobs",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed job pages only; do not bypass membership access."),
    JobSearchSource(id="remote_ok_asia", name="Remote of Asia", url="https://remoteok.io/asia",
                    method="web_search", enabled_by_default=True,
                    note="Search public indexed opportunity pages; verify every result at the employer source."),
    JobSearchSource(id="remote_rocketship", name="Remote Rocketship", url="https://www.remoterocketship.com/",
                    method="public_page", enabled_by_default=True,
                    note="Public remote-job index with country filters."),
)

SOURCES_BY_ID = {source.id: source for source in SOURCE_CATALOG}
DEFAULT_SOURCE_IDS = [source.id for source in SOURCE_CATALOG if source.enabled_by_default]
ALL_SOURCE_IDS = [source.id for source in SOURCE_CATALOG]


def validate_source_ids(source_ids: list[str]) -> list[str]:
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Job search source identifiers must be unique.")
    unknown = [source_id for source_id in source_ids if source_id not in SOURCES_BY_ID]
    if unknown:
        raise ValueError("Unknown job search sources: " + ", ".join(unknown))
    disabled = [source_id for source_id in source_ids if not SOURCES_BY_ID[source_id].available]
    if disabled:
        raise ValueError("Unavailable job search sources cannot be enabled: " + ", ".join(disabled))
    return source_ids


def source_urls(source_ids: list[str]) -> list[str]:
    return [str(SOURCES_BY_ID[source_id].url) for source_id in validate_source_ids(source_ids)]


def _source_url_identity(value: str) -> str:
    """Collapse harmless URL spelling differences without guessing redirects."""
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _source_display_name(value: str) -> str:
    category, separator, name = value.partition(" · ")
    if separator and category in {
        "IMPORTANT", "VC JOB BOARD", "JOBS NEWSLETTER", "VC TALENT NETWORK", "OTHER",
    }:
        return name
    return value


async def quick_save_catalog(enabled: bool = True) -> dict:
    """Expose every saved portal as a public-web discovery source.

    Quick Save already validates public HTTP(S) URLs. A saved portal may be a
    board, newsletter archive, fellowship, or talent network, so the searcher
    uses indexed public pages rather than assuming a feed or automating login.
    """
    rows = await list_quick_job_links(link_type="portal", limit=500)
    items = [{
        "id": f"quick_save:{row['id']}",
        "name": _source_display_name(row["company_name"]),
        "url": row["job_url"],
        "method": "web_search",
        "enabled_by_default": True,
        "note": "Saved in Quick Save; search public pages without signing in.",
        "aliases": [],
        "available": True,
        "enabled": enabled,
        "origin": "quick_save",
    } for row in rows]
    return {
        "items": items,
        "enabled": enabled,
        "enabled_count": len(items) if enabled else 0,
        "available_count": len(items),
        "total_count": len(items),
    }


async def resolved_source_urls(
    source_ids: list[str] | None = None, *, include_quick_save: bool = True,
) -> list[str]:
    """Resolve the immutable, de-duplicated URL set assigned to every run.

    The arguments remain for compatibility with older callers and saved rows;
    source selection is no longer operator-configurable.
    """
    urls = source_urls(ALL_SOURCE_IDS)
    urls.extend(item["url"] for item in (await quick_save_catalog(True))["items"])
    seen: set[str] = set()
    unique: list[str] = []
    for value in urls:
        identity = _source_url_identity(value)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(value)
    return unique


async def all_source_catalog() -> dict:
    """One read-only, de-duplicated catalog used by every search."""
    static = catalog_payload(ALL_SOURCE_IDS)["items"]
    quick = (await quick_save_catalog(True))["items"]
    seen: set[str] = set()
    items: list[dict] = []
    for item in [*static, *quick]:
        identity = _source_url_identity(item["url"])
        if identity in seen:
            continue
        seen.add(identity)
        items.append({**item, "enabled": True, "available": True})
    return {
        "items": items,
        "enabled_count": len(items),
        "available_count": len(items),
        "total_count": len(items),
    }


def catalog_payload(enabled_ids: list[str]) -> dict:
    enabled = set(enabled_ids)
    items = []
    for source in SOURCE_CATALOG:
        item = source.model_dump(mode="json")
        item.update({"available": source.available, "enabled": source.id in enabled})
        items.append(item)
    return {
        "items": items,
        "enabled_count": sum(item["enabled"] for item in items),
        "available_count": sum(item["available"] for item in items),
        "total_count": len(items),
    }
