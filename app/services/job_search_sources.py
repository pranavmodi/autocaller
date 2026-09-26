"""Curated discovery sources for the Job Agent search profile.

The catalog is operator-visible configuration, not evidence that a job is live.
Every discovered role still goes through the existing employer/job verifier.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class JobSearchSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    name: str
    url: HttpUrl
    method: Literal["public_api", "public_feed", "public_page", "web_search", "disabled"]
    enabled_by_default: bool = False
    note: str
    aliases: list[str] = Field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.method != "disabled"


# The user's 30-item list normalizes to 27 distinct sources. AngelList is now
# Wellfound; Remotees and Remote OK Europe were duplicated in the supplied list.
# Obvious link errors are corrected here rather than persisted as broken input.
SOURCE_CATALOG = (
    JobSearchSource(id="remotive", name="Remotive", url="https://remotive.com/feed",
                    method="public_feed", enabled_by_default=True,
                    note="Public RSS feed; retain Remotive attribution on discovered jobs."),
    JobSearchSource(id="toptal", name="Toptal", url="https://www.toptal.com/talent/apply",
                    method="disabled", note="Talent marketplace and screening funnel, not a public job feed."),
    JobSearchSource(id="wellfound", name="Wellfound", url="https://wellfound.com/jobs",
                    method="web_search", enabled_by_default=True,
                    note="Discover public job pages through web search; do not automate account-only flows.",
                    aliases=["AngelList"]),
    JobSearchSource(id="pangian", name="Pangian", url="https://pangian.com/",
                    method="disabled", note="The public job service is currently unavailable/under maintenance."),
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
                    method="disabled", note="Most listing access is subscription-gated."),
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
                    method="disabled", note="Account-based freelance marketplace, outside the standard job-application flow."),
    JobSearchSource(id="freelancer", name="Freelancer", url="https://www.freelancer.com/jobs/",
                    method="disabled", note="Bid-based freelance marketplace, outside the standard job-application flow."),
    JobSearchSource(id="outsourcely", name="Outsourcely", url="https://www.outsourcely.com/remote-workers",
                    method="disabled", note="Account-based talent marketplace rather than a reliable public job feed."),
    JobSearchSource(id="simplyhired", name="SimplyHired", url="https://www.simplyhired.com/search?q=remote",
                    method="web_search", enabled_by_default=True,
                    note="Use indexed public result/job pages and verify every role at the employer source."),
    JobSearchSource(id="remote_in_europe", name="Remote in Europe", url="https://remoteineurope.com/",
                    method="public_page", enabled_by_default=True,
                    note="Public Europe-focused remote-job board.", aliases=["Remote OK Europe"]),
    JobSearchSource(id="remotehabits", name="RemoteHabits", url="https://remotehabits.com/",
                    method="disabled", note="Remote-work content/community site, not a dependable current job board."),
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
                    method="disabled", note="Could not verify a dependable current public listing surface."),
    JobSearchSource(id="we_work_remotely", name="We Work Remotely", url="https://weworkremotely.com/remote-jobs.rss",
                    method="public_feed", enabled_by_default=True,
                    note="Public RSS feed; attribute and link back to the source listing."),
    JobSearchSource(id="remote_freelance", name="Remote Freelance", url="https://remotefreelance.com/",
                    method="disabled", note="Could not verify a dependable current public listing surface."),
    JobSearchSource(id="stackoverflow_jobs", name="Stack Overflow Jobs", url="https://stackoverflow.jobs/",
                    method="web_search", enabled_by_default=True,
                    note="Public technology-job search powered by Indeed; verify at the employer source."),
    JobSearchSource(id="virtual_vocations", name="Virtual Vocations", url="https://www.virtualvocations.com/jobs",
                    method="disabled", note="Listing access is substantially membership-gated."),
    JobSearchSource(id="remote_ok_asia", name="Remote of Asia", url="https://remoteok.io/asia",
                    method="disabled", note="The supplied short link resolves to a stale/unverified regional index."),
    JobSearchSource(id="remote_rocketship", name="Remote Rocketship", url="https://www.remoterocketship.com/",
                    method="public_page", enabled_by_default=True,
                    note="Public remote-job index with country filters."),
)

SOURCES_BY_ID = {source.id: source for source in SOURCE_CATALOG}
DEFAULT_SOURCE_IDS = [source.id for source in SOURCE_CATALOG if source.enabled_by_default]


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
