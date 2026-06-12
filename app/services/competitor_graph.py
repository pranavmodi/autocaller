"""Build a local PI firm competition graph from cached Mission Control data.

The v1 case-mix tagger is deterministic by design because this rebuild must
not spend LLM/gateway capacity. Keep the tagger behind small pure functions so
it can be swapped for a richer classifier later without changing the graph
schema, API, or CLI contract.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, desc, func, or_, select

from app.db import AsyncSessionLocal
from app.db.models import CompetitorEdgeRow, FirmCompetitiveFeatureRow, FrontFirmActivityRow
from app.services.front_sync import MISSION_DB_PATH, extract_emails, normalize_domain


CASE_CATEGORIES = ("mva", "premises", "dog_bite", "med_mal", "workers_comp", "other")
VALUE_TIERS = ("small", "mid", "large")
VALUE_TIER_RANK = {"small": 0, "mid": 1, "large": 2}

CONSUMER_DOMAINS = {
    "aol.com",
    "gmail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "me.com",
    "msn.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}

STATE_NAMES = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "ILLINOIS": "IL",
    "MICHIGAN": "MI",
    "NEVADA": "NV",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "OREGON": "OR",
    "TEXAS": "TX",
    "WASHINGTON": "WA",
}

CA_CITY_TO_METRO = {
    # Los Angeles / San Fernando Valley / South Bay
    "agoura hills": "los-angeles",
    "alhambra": "los-angeles",
    "arcadia": "los-angeles",
    "baldwin park": "los-angeles",
    "beverly hills": "los-angeles",
    "burbank": "los-angeles",
    "calabasas": "los-angeles",
    "canoga park": "los-angeles",
    "carson": "los-angeles",
    "century city": "los-angeles",
    "chatsworth": "los-angeles",
    "compton": "los-angeles",
    "culver city": "los-angeles",
    "downey": "los-angeles",
    "el monte": "los-angeles",
    "el segundo": "los-angeles",
    "encino": "los-angeles",
    "gardena": "los-angeles",
    "glendale": "los-angeles",
    "granada hills": "los-angeles",
    "hawthorne": "los-angeles",
    "hermosa beach": "los-angeles",
    "inglewood": "los-angeles",
    "lancaster": "los-angeles",
    "lawndale": "los-angeles",
    "long beach": "los-angeles",
    "los angeles": "los-angeles",
    "manhattan beach": "los-angeles",
    "marina del rey": "los-angeles",
    "monrovia": "los-angeles",
    "north hollywood": "los-angeles",
    "northridge": "los-angeles",
    "palmdale": "los-angeles",
    "panorama city": "los-angeles",
    "pasadena": "los-angeles",
    "redondo beach": "los-angeles",
    "santa clarita": "los-angeles",
    "santa monica": "los-angeles",
    "sherman oaks": "los-angeles",
    "studio city": "los-angeles",
    "tarzana": "los-angeles",
    "torrance": "los-angeles",
    "valencia": "los-angeles",
    "valley village": "los-angeles",
    "van nuys": "los-angeles",
    "west covina": "los-angeles",
    "west hills": "los-angeles",
    "west hollywood": "los-angeles",
    "westlake village": "los-angeles",
    "whittier": "los-angeles",
    "woodland hills": "los-angeles",
    # Orange County
    "anaheim": "orange-county",
    "anaheim hills": "orange-county",
    "brea": "orange-county",
    "buena park": "orange-county",
    "costa mesa": "orange-county",
    "fountain valley": "orange-county",
    "fullerton": "orange-county",
    "garden grove": "orange-county",
    "huntington beach": "orange-county",
    "irvine": "orange-county",
    "la habra": "orange-county",
    "la mirada": "orange-county",
    "laguna beach": "orange-county",
    "mission viejo": "orange-county",
    "newport beach": "orange-county",
    "orange": "orange-county",
    "santa ana": "orange-county",
    "seal beach": "orange-county",
    "tustin": "orange-county",
    "yorba linda": "orange-county",
    # Inland Empire
    "chino": "inland-empire",
    "chino hills": "inland-empire",
    "colton": "inland-empire",
    "corona": "inland-empire",
    "fontana": "inland-empire",
    "menifee": "inland-empire",
    "murrieta": "inland-empire",
    "ontario": "inland-empire",
    "palm desert": "inland-empire",
    "pomona": "inland-empire",
    "rancho cucamonga": "inland-empire",
    "redlands": "inland-empire",
    "riverside": "inland-empire",
    "san bernardino": "inland-empire",
    "temecula": "inland-empire",
    "upland": "inland-empire",
    # San Diego
    "carlsbad": "san-diego",
    "chula vista": "san-diego",
    "el cajon": "san-diego",
    "encinitas": "san-diego",
    "escondido": "san-diego",
    "la jolla": "san-diego",
    "oceanside": "san-diego",
    "san diego": "san-diego",
    "san marcos": "san-diego",
    "vista": "san-diego",
    # Bay Area
    "concord": "sf-bay",
    "dublin": "sf-bay",
    "fremont": "sf-bay",
    "hayward": "sf-bay",
    "milpitas": "sf-bay",
    "oakland": "sf-bay",
    "palo alto": "sf-bay",
    "pleasanton": "sf-bay",
    "redwood city": "sf-bay",
    "san francisco": "sf-bay",
    "san jose": "sf-bay",
    "san mateo": "sf-bay",
    "san rafael": "sf-bay",
    "santa clara": "sf-bay",
    "walnut creek": "sf-bay",
    # Sacramento / Central California / Coast
    "davis": "sacramento",
    "fair oaks": "sacramento",
    "roseville": "sacramento",
    "sacramento": "sacramento",
    "yuba city": "sacramento",
    "bakersfield": "central-valley",
    "fresno": "central-valley",
    "merced": "central-valley",
    "modesto": "central-valley",
    "stockton": "central-valley",
    "turlock": "central-valley",
    "capitola": "central-coast",
    "monterey": "central-coast",
    "oxnard": "central-coast",
    "san luis obispo": "central-coast",
    "santa barbara": "central-coast",
    "santa cruz": "central-coast",
    "santa maria": "central-coast",
    "ventura": "central-coast",
}

CA_METRO_ADJACENCY = {
    "los-angeles": {"orange-county", "inland-empire", "central-coast"},
    "orange-county": {"los-angeles", "inland-empire", "san-diego"},
    "inland-empire": {"los-angeles", "orange-county", "san-diego", "central-valley"},
    "san-diego": {"orange-county", "inland-empire"},
    "sf-bay": {"sacramento", "central-valley", "central-coast"},
    "sacramento": {"sf-bay", "central-valley"},
    "central-valley": {"sacramento", "sf-bay", "inland-empire", "central-coast"},
    "central-coast": {"los-angeles", "sf-bay", "central-valley"},
}

CASE_KEYWORDS = {
    "mva": (
        "auto accident",
        "car accident",
        "vehicle accident",
        "motor vehicle",
        "mva",
        "collision",
        "rear end",
        "rear-end",
        "motorcycle",
        "pedestrian",
        "truck accident",
        "commercial mva",
        "uber",
        "lyft",
    ),
    "premises": (
        "premises",
        "slip and fall",
        "trip and fall",
        "fall down",
        "negligent security",
        "property",
        "store fall",
        "landlord",
    ),
    "dog_bite": ("dog bite", "dog attack", "animal attack", "canine"),
    "med_mal": (
        "medical malpractice",
        "med mal",
        "malpractice",
        "hospital negligence",
        "doctor negligence",
        "nursing home",
    ),
    "workers_comp": (
        "workers comp",
        "workers' comp",
        "workers compensation",
        "work injury",
        "workplace injury",
        "industrial injury",
    ),
}

ADDRESS_RE = re.compile(
    r"(?P<city>[A-Za-z][A-Za-z .'\-/]{1,90})\s*,\s*"
    r"(?P<state>[A-Z]{2}|California|Nevada|Texas|Arizona|Florida|Illinois|Michigan|Oregon|Washington)"
    r"\.?,?\s*(?P<zip>\d{5})(?:-\d{4})?\b",
    re.I,
)
LOOSE_ADDRESS_RE = re.compile(
    r"(?P<city>[A-Za-z][A-Za-z .'\-/]{1,90})\s+"
    r"(?P<state>CA|NV|TX|AZ|FL|IL|MI|OR|WA)"
    r"\.?\s*(?P<zip>\d{5})(?:-\d{4})?\b",
    re.I,
)
AMOUNT_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.\d{1,2})?|[0-9]+(?:\.\d{1,2})?)")
SWITCHING_RE = re.compile(
    r"substitution of attorney|no longer represents|case has been transferred to|new counsel",
    re.I,
)


@dataclass(frozen=True)
class AddressParts:
    city: str | None
    state: str | None
    metro: str | None
    zip_code: str | None = None


@dataclass(frozen=True)
class CachedMessage:
    conversation_id: str
    subject: str
    author_email: str
    body_text: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def _state_code(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().replace(".", "")
    if len(raw) == 2:
        return raw.upper()
    return STATE_NAMES.get(raw.upper())


def _title_city(value: str) -> str:
    return " ".join(part.capitalize() for part in value.strip().split())


def _clean_city(raw: str, state: str | None) -> str | None:
    clean = re.sub(r"\s+", " ", raw.replace("|", " ").replace("/", " ")).strip(" ,.;:-")
    clean = re.sub(r"^(?:po box|p\.o\. box)\s+\d+\s+", "", clean, flags=re.I)
    clean = re.sub(r"\b(?:suite|ste|floor|fl|unit|#)\s*[A-Za-z0-9.-]+\b", " ", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" ,.;:-")
    if state == "CA":
        lower = clean.lower()
        for city in sorted(CA_CITY_TO_METRO, key=len, reverse=True):
            if lower == city or lower.endswith(f" {city}"):
                return _title_city(city)
    words = re.findall(r"[A-Za-z][A-Za-z.'-]*", clean)
    if not words:
        return None
    street_words = {
        "blvd",
        "boulevard",
        "street",
        "st",
        "ave",
        "avenue",
        "drive",
        "dr",
        "road",
        "rd",
        "place",
        "pl",
        "court",
        "ct",
        "floor",
    }
    tail = []
    for word in reversed(words):
        if word.lower().strip(".") in street_words:
            break
        tail.append(word)
        if len(tail) == 3:
            break
    if not tail:
        return None
    return _title_city(" ".join(reversed(tail)))


def _first_address(addresses: Any) -> str | None:
    parsed = _safe_json(addresses, [])
    if isinstance(parsed, list) and parsed:
        return str(parsed[0])
    if isinstance(addresses, str) and addresses.strip() and not addresses.strip().startswith("["):
        return addresses.strip()
    return None


def parse_first_address(addresses: Any) -> AddressParts:
    address = _first_address(addresses)
    if not address:
        return AddressParts(city=None, state=None, metro=None)
    matches = list(ADDRESS_RE.finditer(address)) or list(LOOSE_ADDRESS_RE.finditer(address))
    if not matches:
        return AddressParts(city=None, state=None, metro=None)
    match = matches[-1]
    state = _state_code(match.group("state"))
    city = _clean_city(match.group("city"), state)
    if not state:
        return AddressParts(city=city, state=None, metro=None, zip_code=match.group("zip"))
    if not city:
        return AddressParts(city=None, state=state, metro=f"state:{state}", zip_code=match.group("zip"))
    if state == "CA":
        metro = CA_CITY_TO_METRO.get(city.lower(), "state:CA")
    else:
        metro = f"state:{state}"
    return AddressParts(city=city, state=state, metro=metro, zip_code=match.group("zip"))


def tag_case_text(text: str) -> set[str]:
    """Return deterministic case categories for one thread text blob.

    This is intentionally swappable: callers consume only the category set and
    normalized mix, not the keyword implementation.
    """
    lower = text.lower()
    tags = {category for category, needles in CASE_KEYWORDS.items() if any(needle in lower for needle in needles)}
    return tags or {"other"}


def case_mix_for_texts(texts: Iterable[str]) -> dict[str, float]:
    counts = Counter()
    for text in texts:
        for tag in tag_case_text(text):
            counts[tag] += 1
    total = sum(counts.values())
    if total <= 0:
        return {"other": 1.0}
    return {category: round(counts.get(category, 0) / total, 4) for category in CASE_CATEGORIES if counts.get(category, 0)}


def extract_dollar_amounts(text: str) -> list[float]:
    amounts = []
    for match in AMOUNT_RE.finditer(text):
        try:
            amount = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if amount >= 100:
            amounts.append(amount)
    return amounts


def value_tier_for_amounts(amounts: Sequence[float]) -> tuple[str | None, float | None]:
    if not amounts:
        return None, None
    med = float(median(amounts))
    if med < 5_000:
        return "small", med
    if med <= 25_000:
        return "mid", med
    return "large", med


def case_mix_cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(float(a.get(category, 0)) * float(b.get(category, 0)) for category in CASE_CATEGORIES)
    a_norm = math.sqrt(sum(float(a.get(category, 0)) ** 2 for category in CASE_CATEGORIES))
    b_norm = math.sqrt(sum(float(b.get(category, 0)) ** 2 for category in CASE_CATEGORIES))
    if a_norm <= 0 or b_norm <= 0:
        return 0.0
    return round(dot / (a_norm * b_norm), 4)


def value_tier_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if abs(VALUE_TIER_RANK.get(a, -9) - VALUE_TIER_RANK.get(b, 9)) == 1:
        return 0.5
    return 0.0


def _domain_candidates(website: str | None, emails: Any) -> set[str]:
    domains: set[str] = set()
    for candidate in [website, *extract_emails(emails)]:
        domain = normalize_domain(str(candidate or ""))
        if domain and domain not in CONSUMER_DOMAINS:
            domains.add(domain)
    for email in _safe_json(emails, []):
        domain = normalize_domain(str(email))
        if domain and domain not in CONSUMER_DOMAINS:
            domains.add(domain)
    return domains


def _primary_domain(website: str | None, emails: Any) -> str | None:
    domain = normalize_domain(website)
    if domain and domain not in CONSUMER_DOMAINS and "filevineapp.com" not in domain:
        return domain
    for candidate in sorted(_domain_candidates(website, emails)):
        if "filevineapp.com" not in candidate:
            return candidate
    return next(iter(sorted(_domain_candidates(website, emails))), None)


def _load_cache(db_path: Path) -> tuple[list[dict[str, Any]], dict[str, list[CachedMessage]], dict[str, list[CachedMessage]], dict[str, list[CachedMessage]]]:
    # mode=ro only — never immutable=1: the lien cron writes this DB every 4h,
    # and immutable disables the locking that makes concurrent reads safe.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        firms = [
            {
                "pif_id": str(row[0]),
                "firm_name": str(row[1] or ""),
                "website": row[2],
                "emails": row[3],
                "addresses": row[4],
                "conversation_ids": _safe_json(row[5], []),
            }
            for row in conn.execute(
                "SELECT id, firm_name, website, emails, addresses, conversation_ids FROM pif_firms"
            )
        ]
        subjects = {str(row[0]): str(row[1] or "") for row in conn.execute("SELECT id, subject FROM front_conversations")}
        by_conversation: dict[str, list[CachedMessage]] = defaultdict(list)
        by_email: dict[str, list[CachedMessage]] = defaultdict(list)
        by_domain: dict[str, list[CachedMessage]] = defaultdict(list)
        for conversation_id, author_email, body_text in conn.execute(
            "SELECT conversation_id, author_email, body_text FROM front_messages"
        ):
            email = str(author_email or "").strip().lower()
            domain = normalize_domain(email)
            message = CachedMessage(
                conversation_id=str(conversation_id or ""),
                subject=subjects.get(str(conversation_id or ""), ""),
                author_email=email,
                body_text=str(body_text or ""),
            )
            by_conversation[message.conversation_id].append(message)
            if email:
                by_email[email].append(message)
            if domain:
                by_domain[domain].append(message)
        return firms, by_conversation, by_email, by_domain
    finally:
        conn.close()


def _firm_messages(
    firm: dict[str, Any],
    by_conversation: dict[str, list[CachedMessage]],
    by_email: dict[str, list[CachedMessage]],
    by_domain: dict[str, list[CachedMessage]],
) -> list[CachedMessage]:
    seen: set[tuple[str, str, str]] = set()
    messages: list[CachedMessage] = []

    def add_many(rows: Iterable[CachedMessage]) -> None:
        for row in rows:
            key = (row.conversation_id, row.author_email, row.body_text[:80])
            if key not in seen:
                seen.add(key)
                messages.append(row)

    conversation_ids = [str(conversation_id) for conversation_id in (firm.get("conversation_ids") or [])]
    for conversation_id in conversation_ids:
        add_many(by_conversation.get(str(conversation_id), []))
    if conversation_ids:
        return messages
    for email in extract_emails(firm.get("emails")):
        add_many(by_email.get(email.lower(), []))
    for domain in _domain_candidates(firm.get("website"), firm.get("emails")):
        add_many(by_domain.get(domain, []))
    return messages


def _thread_texts(messages: Sequence[CachedMessage]) -> list[tuple[str, str]]:
    grouped: dict[str, list[CachedMessage]] = defaultdict(list)
    for message in messages:
        grouped[message.conversation_id].append(message)
    texts = []
    for conversation_id, rows in grouped.items():
        subject = next((row.subject for row in rows if row.subject), "")
        body = "\n".join(row.body_text for row in rows if row.body_text)
        texts.append((subject, f"{subject}\n{body}".strip()))
    return texts


def _active_orbit(front_activity: dict[str, dict[str, Any]], pif_id: str, now: datetime) -> float:
    activity = front_activity.get(pif_id)
    if not activity:
        return 0.0
    last_seen = activity.get("last_seen_at")
    if isinstance(last_seen, datetime) and last_seen >= now - timedelta(days=90):
        return 1.0
    return 0.5


def _pair_id(a: str, b: str) -> str:
    digest = hashlib.sha1(f"{a}:{b}".encode("utf-8")).hexdigest()[:24]
    return f"comp_{digest}"


def _edge_score(
    a: dict[str, Any],
    b: dict[str, Any],
    front_activity: dict[str, dict[str, Any]],
    switch_evidence: dict[tuple[str, str], list[dict[str, Any]]],
    now: datetime,
) -> tuple[float, dict[str, float]]:
    same_metro = a["metro"] == b["metro"]
    adjacent = b["metro"] in CA_METRO_ADJACENCY.get(a["metro"], set())
    geo = 1.0 if same_metro else 0.4 if adjacent else 0.0
    if geo <= 0:
        return 0.0, {"geo": 0.0}
    case_mix = case_mix_cosine(a["case_mix"], b["case_mix"])
    value = value_tier_similarity(a.get("value_tier"), b.get("value_tier"))
    orbit = min(_active_orbit(front_activity, a["pif_id"], now), _active_orbit(front_activity, b["pif_id"], now))
    pair = tuple(sorted((a["pif_id"], b["pif_id"])))
    switch = 1.0 if switch_evidence.get(pair) else 0.0
    raw = (0.52 * case_mix) + (0.23 * value) + (0.15 * orbit) + (0.10 * switch)
    score = max(0.0, min(1.0, geo * raw))
    if switch:
        score = max(score, 0.65 if same_metro else 0.45)
    return round(score, 4), {
        "geo": geo,
        "case_mix": case_mix,
        "value_tier": value,
        "shared_orbit": orbit,
        "client_switching": switch,
    }


def _edge_evidence(
    a: dict[str, Any],
    b: dict[str, Any],
    components: dict[str, float],
    switch_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    why = []
    if components.get("geo") == 1.0:
        why.append(f"same metro: {a['metro']}")
    elif components.get("geo"):
        why.append(f"adjacent metros: {a['metro']} / {b['metro']}")
    why.append(f"case mix similarity {components.get('case_mix', 0):.2f}")
    if components.get("value_tier"):
        why.append(f"lien/bill tier proximity {components['value_tier']:.1f}")
    if components.get("shared_orbit"):
        why.append("both have cached Front activity")
    if switch_rows:
        why.append("substitution/new-counsel language found")
    return {
        "why": "; ".join(why),
        "firm_a": {
            "name": a["firm_name"],
            "domain": a.get("domain"),
            "value_tier": a.get("value_tier"),
            "case_mix": a.get("case_mix"),
        },
        "firm_b": {
            "name": b["firm_name"],
            "domain": b.get("domain"),
            "value_tier": b.get("value_tier"),
            "case_mix": b.get("case_mix"),
        },
        "client_switching": switch_rows[:3],
    }


def _firm_alias(feature: dict[str, Any]) -> str:
    name = re.sub(
        r"\b(?:law offices of|law office of|the|a professional corporation|aplc|llp|pc|inc|incorporated)\b",
        "",
        feature["firm_name"].lower(),
    )
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _switch_alias_indexes(features: Sequence[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[tuple[str, str]]]]:
    domains: dict[str, str] = {}
    aliases_by_first_token: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for feature in features:
        domain = (feature.get("domain") or "").lower()
        if domain:
            domains[domain] = feature["pif_id"]
        alias = _firm_alias(feature)
        if len(alias) >= 8:
            first = alias.split(" ", 1)[0]
            aliases_by_first_token[first].append((alias, feature["pif_id"]))
    return domains, aliases_by_first_token


def _names_in_text(
    text: str,
    domain_aliases: dict[str, str],
    aliases_by_first_token: dict[str, list[tuple[str, str]]],
) -> set[str]:
    lower = text.lower()
    normalized = re.sub(r"[^a-z0-9. ]+", " ", lower)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    found = {pif_id for domain, pif_id in domain_aliases.items() if domain in lower}
    tokens = set(normalized.replace(".", " ").split())
    for token in tokens:
        for alias, pif_id in aliases_by_first_token.get(token, []):
            if alias in normalized:
                found.add(pif_id)
    return found


def _client_switching_evidence(features: Sequence[dict[str, Any]], firm_texts: dict[str, list[tuple[str, str]]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    domain_aliases, aliases_by_first_token = _switch_alias_indexes(features)
    for source_pif, texts in firm_texts.items():
        for subject, text in texts:
            if not SWITCHING_RE.search(text):
                continue
            mentioned = _names_in_text(text, domain_aliases, aliases_by_first_token)
            mentioned.add(source_pif)
            if len(mentioned) < 2:
                continue
            excerpt = re.sub(r"\s+", " ", text).strip()[:220]
            for other in sorted(mentioned - {source_pif}):
                pair = tuple(sorted((source_pif, other)))
                evidence[pair].append({
                    "source_pif_id": source_pif,
                    "other_pif_id": other,
                    "subject": subject[:160],
                    "matched_language": excerpt,
                })
    return evidence


def build_competitor_graph_from_cache(
    *,
    mission_db_path: Path = MISSION_DB_PATH,
    front_activities: Sequence[dict[str, Any]] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    firms, by_conversation, by_email, by_domain = _load_cache(mission_db_path)
    front_by_pif = {str(row["pif_id"]): row for row in front_activities if row.get("pif_id")}

    features: list[dict[str, Any]] = []
    firm_texts: dict[str, list[tuple[str, str]]] = {}
    for firm in firms:
        pif_id = firm["pif_id"]
        address = parse_first_address(firm.get("addresses"))
        messages = _firm_messages(firm, by_conversation, by_email, by_domain)
        texts = _thread_texts(messages)
        firm_texts[pif_id] = texts
        case_mix = case_mix_for_texts(text for _, text in texts)
        amounts = [amount for _, text in texts for amount in extract_dollar_amounts(text)]
        value_tier, median_amount = value_tier_for_amounts(amounts)
        sample_subjects = [subject for subject, _ in texts if subject][:5]
        feature = {
            "pif_id": pif_id,
            "firm_name": firm["firm_name"] or pif_id,
            "domain": _primary_domain(firm.get("website"), firm.get("emails")),
            "metro": address.metro,
            "city": address.city,
            "state": address.state,
            "case_mix": case_mix,
            "value_tier": value_tier,
            "volume_proxy": len(texts),
            "evidence": {
                "source": "mission_control_front_cache",
                "amount_kind": "lien_or_bill_amounts",
                "median_lien_or_bill_amount": median_amount,
                "sample_amounts": [round(amount, 2) for amount in amounts[:10]],
                "sample_subjects": sample_subjects,
                "matched_conversations_count": len(texts),
                "first_address": _first_address(firm.get("addresses")),
            },
            "computed_at": now,
        }
        features.append(feature)

    switch_evidence = _client_switching_evidence(features, firm_texts)
    edge_candidates: list[dict[str, Any]] = []
    by_metro: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feature in features:
        if feature.get("metro"):
            by_metro[feature["metro"]].append(feature)

    seen_pairs: set[tuple[str, str]] = set()

    def add_pairs(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]], same_bucket: bool) -> None:
        for i, a in enumerate(rows_a):
            compare_rows = rows_b[i + 1 :] if same_bucket else rows_b
            for b in compare_rows:
                if a["pif_id"] == b["pif_id"]:
                    continue
                pair = tuple(sorted((a["pif_id"], b["pif_id"])))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                score, components = _edge_score(a, b, front_by_pif, switch_evidence, now)
                if score < 0.3:
                    continue
                edge_candidates.append({
                    "id": _pair_id(*pair),
                    "firm_a_pif_id": pair[0],
                    "firm_b_pif_id": pair[1],
                    "metro": a["metro"] if a["metro"] == b["metro"] else f"{a['metro']}+{b['metro']}",
                    "score": score,
                    "components": components,
                    "evidence": _edge_evidence(a, b, components, switch_evidence.get(pair, [])),
                    "computed_at": now,
                })

    for metro, rows in by_metro.items():
        if len(rows) > 200:
            buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                buckets[row.get("value_tier") or "unknown"].append(row)
            for tier, tier_rows in buckets.items():
                add_pairs(tier_rows, tier_rows, True)
                if tier in VALUE_TIER_RANK:
                    for other_tier, other_rows in buckets.items():
                        if other_tier in VALUE_TIER_RANK and VALUE_TIER_RANK[other_tier] == VALUE_TIER_RANK[tier] + 1:
                            add_pairs(tier_rows, other_rows, False)
        else:
            add_pairs(rows, rows, True)
        for adjacent in sorted(CA_METRO_ADJACENCY.get(metro, set())):
            if metro < adjacent:
                add_pairs(rows, by_metro.get(adjacent, []), False)

    degrees: Counter[str] = Counter()
    edges = []
    for edge in sorted(edge_candidates, key=lambda row: row["score"], reverse=True):
        a = edge["firm_a_pif_id"]
        b = edge["firm_b_pif_id"]
        if degrees[a] >= 10 or degrees[b] >= 10:
            continue
        edges.append(edge)
        degrees[a] += 1
        degrees[b] += 1

    return {
        "features": features,
        "edges": edges,
        "client_switching_hit_count": sum(len(rows) for rows in switch_evidence.values()),
        "firms_with_metro": sum(1 for feature in features if feature.get("metro")),
        "firms_with_case_mix": sum(1 for feature in features if feature.get("case_mix")),
    }


async def _load_front_activities() -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FrontFirmActivityRow.pif_id, FrontFirmActivityRow.domain, FrontFirmActivityRow.last_seen_at)
            .where(FrontFirmActivityRow.pif_id.isnot(None))
        )).all()
    return [
        {"pif_id": pif_id, "domain": domain, "last_seen_at": last_seen_at}
        for pif_id, domain, last_seen_at in rows
        if pif_id
    ]


async def rebuild_competitor_graph(*, mission_db_path: Path = MISSION_DB_PATH) -> dict[str, Any]:
    started = time.monotonic()
    front_activities = await _load_front_activities()
    graph = await asyncio.to_thread(
        build_competitor_graph_from_cache,
        mission_db_path=mission_db_path,
        front_activities=front_activities,
    )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(CompetitorEdgeRow))
            await session.execute(delete(FirmCompetitiveFeatureRow))
            session.add_all(FirmCompetitiveFeatureRow(**feature) for feature in graph["features"])
            session.add_all(CompetitorEdgeRow(**edge) for edge in graph["edges"])
    return {
        "firms_with_features": len(graph["features"]),
        "firms_with_metro": graph["firms_with_metro"],
        "firms_with_case_mix": graph["firms_with_case_mix"],
        "edge_count": len(graph["edges"]),
        "client_switching_hit_count": graph["client_switching_hit_count"],
        "duration_seconds": round(time.monotonic() - started, 2),
    }


async def competitor_summary() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        feature_count = (await session.execute(select(func.count(FirmCompetitiveFeatureRow.pif_id)))).scalar_one()
        with_metro = (
            await session.execute(
                select(func.count(FirmCompetitiveFeatureRow.pif_id)).where(FirmCompetitiveFeatureRow.metro.isnot(None))
            )
        ).scalar_one()
        edge_count = (await session.execute(select(func.count(CompetitorEdgeRow.id)))).scalar_one()
        last_computed = (await session.execute(select(func.max(FirmCompetitiveFeatureRow.computed_at)))).scalar_one()
        metro_rows = (await session.execute(
            select(FirmCompetitiveFeatureRow.metro, func.count(FirmCompetitiveFeatureRow.pif_id))
            .where(FirmCompetitiveFeatureRow.metro.isnot(None))
            .group_by(FirmCompetitiveFeatureRow.metro)
            .order_by(desc(func.count(FirmCompetitiveFeatureRow.pif_id)))
        )).all()
        tier_rows = (await session.execute(
            select(FirmCompetitiveFeatureRow.value_tier, func.count(FirmCompetitiveFeatureRow.pif_id))
            .group_by(FirmCompetitiveFeatureRow.value_tier)
        )).all()
    return {
        "firms_with_features": int(feature_count or 0),
        "firms_with_metro": int(with_metro or 0),
        "edge_count": int(edge_count or 0),
        "last_computed_at": last_computed.isoformat() if last_computed else None,
        "metro_counts": [{"metro": metro, "count": int(count or 0)} for metro, count in metro_rows],
        "tier_distribution": {str(tier or "unknown"): int(count or 0) for tier, count in tier_rows},
    }


async def get_competitors(*, domain: str = "", pif_id: str = "", q: str = "", limit: int = 10) -> dict[str, Any]:
    identifier = (pif_id or domain or q).strip()
    async with AsyncSessionLocal() as session:
        firm = None
        if pif_id:
            firm = await session.get(FirmCompetitiveFeatureRow, pif_id)
        if firm is None and domain:
            firm = (await session.execute(
                select(FirmCompetitiveFeatureRow).where(FirmCompetitiveFeatureRow.domain == normalize_domain(domain)).limit(1)
            )).scalar_one_or_none()
        if firm is None and identifier:
            like = f"%{identifier}%"
            firm = (await session.execute(
                select(FirmCompetitiveFeatureRow)
                .where(or_(FirmCompetitiveFeatureRow.firm_name.ilike(like), FirmCompetitiveFeatureRow.domain.ilike(like)))
                .order_by(FirmCompetitiveFeatureRow.firm_name)
                .limit(1)
            )).scalar_one_or_none()
        if firm is None:
            return {"firm": None, "competitors": []}
        rows = (await session.execute(
            select(CompetitorEdgeRow, FirmCompetitiveFeatureRow)
            .join(
                FirmCompetitiveFeatureRow,
                or_(
                    FirmCompetitiveFeatureRow.pif_id == CompetitorEdgeRow.firm_a_pif_id,
                    FirmCompetitiveFeatureRow.pif_id == CompetitorEdgeRow.firm_b_pif_id,
                ),
            )
            .where(or_(CompetitorEdgeRow.firm_a_pif_id == firm.pif_id, CompetitorEdgeRow.firm_b_pif_id == firm.pif_id))
            .where(FirmCompetitiveFeatureRow.pif_id != firm.pif_id)
            .order_by(desc(CompetitorEdgeRow.score))
            .limit(max(1, min(limit, 50)))
        )).all()
    return {
        "firm": _feature_payload(firm),
        "competitors": [
            {
                "pif_id": neighbor.pif_id,
                "firm_name": neighbor.firm_name,
                "domain": neighbor.domain,
                "metro": neighbor.metro,
                "score": round(float(edge.score), 4),
                "components": edge.components or {},
                "evidence": edge.evidence or {},
            }
            for edge, neighbor in rows
        ],
    }


def _feature_payload(row: FirmCompetitiveFeatureRow) -> dict[str, Any]:
    return {
        "pif_id": row.pif_id,
        "firm_name": row.firm_name,
        "domain": row.domain,
        "metro": row.metro,
        "city": row.city,
        "state": row.state,
        "case_mix": row.case_mix or {},
        "value_tier": row.value_tier,
        "volume_proxy": row.volume_proxy,
        "evidence": row.evidence or {},
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }
