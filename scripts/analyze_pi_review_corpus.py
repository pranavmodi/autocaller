#!/usr/bin/env python3
"""Freeze and aggregate the source-backed PI law-firm review corpus."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import psycopg2


ANALYSIS_VERSION = "pi_review_analysis_v1"
CLASSIFICATION_VERSION = "pi_reviews_v1"
TARGET = 5_000
INDEPENDENT_SOURCES = {
    "google", "yelp", "avvo", "bbb", "facebook", "reviews.io",
    "trustpilot", "martindale", "lawyers.com", "findlaw",
}
CURATED_SOURCES = {"official_testimonials", "official_website"}
AGGREGATOR_SOURCES = {
    "birdeye", "bestprosintown", "trustanalytica", "legaldirectorate",
    "attorneyatlaw", "lawyer_com", "revdex",
}


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def text_hash(value: Any) -> str:
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def pct(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def label(value: str) -> str:
    return value.replace("_", " ").replace(".io", ".io").title()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else ["label", "count"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_records(snapshot_at: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    dsn = os.getenv("DATABASE_URL", "postgresql://autocaller:dev@localhost:5432/autocaller")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT fr.pif_id, f.firm_name, fr.reviews_json
                FROM firm_reviews fr
                JOIN pif_directory_firms f ON f.id = fr.pif_id
                WHERE f.entity_type IN ('pi_law_firm', 'personal_injury_law_firm')
                """
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    raw_count = 0
    excluded_after_snapshot = 0
    deduped: dict[tuple[str, ...], dict[str, Any]] = {}
    for firm_id, firm_name, payload in rows:
        data = payload if isinstance(payload, dict) else {}
        for source_block in data.get("sources") or []:
            if not isinstance(source_block, dict):
                continue
            source = str(source_block.get("source") or "other").strip().lower()
            listing_url = str(source_block.get("listing_url") or "").strip()
            if not listing_url.startswith(("http://", "https://")):
                continue
            for review in source_block.get("reviews") or []:
                if not isinstance(review, dict) or not str(review.get("text") or "").strip():
                    continue
                raw_count += 1
                collected_at = parse_time(review.get("collected_at"))
                if collected_at and collected_at > snapshot_at:
                    excluded_after_snapshot += 1
                    continue
                review_hash = str(review.get("text_hash") or text_hash(review.get("text")))
                key = (
                    str(firm_id), source, listing_url.lower().rstrip("/"),
                    normalized_text(review.get("reviewer_name")),
                    str(review.get("review_date") or ""), review_hash,
                )
                classification = review.get("classification") if isinstance(review.get("classification"), dict) else {}
                deduped.setdefault(key, {
                    "firm_id": str(firm_id),
                    "firm_name": str(firm_name or ""),
                    "source": source,
                    "listing_url": listing_url,
                    "review_url": review.get("review_url"),
                    "reviewer_name": review.get("reviewer_name"),
                    "rating": review.get("rating"),
                    "review_date": review.get("review_date"),
                    "text_hash": review_hash,
                    "classification": classification,
                })

    records = list(deduped.values())
    sources_by_firm_text: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record in records:
        sources_by_firm_text[(record["firm_id"], record["text_hash"])].add(record["source"])
    for record in records:
        record["cross_source_republication"] = len(
            sources_by_firm_text[(record["firm_id"], record["text_hash"])]
        ) > 1
        if record["source"] in CURATED_SOURCES:
            record["source_group"] = "curated_testimonial"
        elif record["source"] in AGGREGATOR_SOURCES:
            record["source_group"] = "aggregator"
        elif record["source"] in INDEPENDENT_SOURCES:
            record["source_group"] = "independent"
        else:
            record["source_group"] = "other_public_source"
    return records, {
        "raw_rows_examined": raw_count,
        "deduplicated_records": raw_count - excluded_after_snapshot - len(records),
        "excluded_after_snapshot": excluded_after_snapshot,
    }


def count_labels(records: Iterable[dict[str, Any]], field: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for record in records:
        values = record["classification"].get(field) or []
        if not isinstance(values, list):
            values = [values]
        result.update(str(value) for value in set(values) if value)
    return result


def theme_counts(records: Iterable[dict[str, Any]]) -> tuple[Counter[str], Counter[str]]:
    positive: Counter[str] = Counter()
    negative: Counter[str] = Counter()
    for record in records:
        seen_positive: set[str] = set()
        seen_negative: set[str] = set()
        for item in record["classification"].get("themes") or []:
            if not isinstance(item, dict) or not item.get("theme"):
                continue
            if item.get("sentiment") == "positive":
                seen_positive.add(str(item["theme"]))
            elif item.get("sentiment") == "negative":
                seen_negative.add(str(item["theme"]))
        positive.update(seen_positive)
        negative.update(seen_negative)
    return positive, negative


def firm_balanced(records: list[dict[str, Any]], extractor) -> dict[str, float]:
    by_firm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_firm[record["firm_id"]].append(record)
    labels = sorted({item for firm_records in by_firm.values() for item in extractor(firm_records)})
    result: dict[str, float] = {}
    for item in labels:
        rates = []
        for firm_records in by_firm.values():
            matches = sum(1 for record in firm_records if item in extractor([record]))
            rates.append(matches / len(firm_records))
        result[item] = round(sum(rates) / len(rates) * 100, 2) if rates else 0.0
    return result


def list_field_extractor(field: str):
    def extract(records: list[dict[str, Any]]) -> set[str]:
        values: set[str] = set()
        for record in records:
            raw = record["classification"].get(field) or []
            values.update(str(value) for value in raw if value and value != "unknown")
        return values
    return extract


def analyze(records: list[dict[str, Any]], snapshot_at: datetime, load_stats: dict[str, int]) -> dict[str, Any]:
    included = [record for record in records if not record["cross_source_republication"]]
    independent = [record for record in included if record["source_group"] == "independent"]
    classified = [
        record for record in included
        if record["classification"].get("classification_version") == CLASSIFICATION_VERSION
    ]
    independent_classified = [record for record in independent if record in classified]
    positive_records = [
        record for record in independent_classified
        if record["classification"].get("overall_sentiment") == "positive"
    ]
    negative_records = [
        record for record in independent_classified
        if record["classification"].get("overall_sentiment") in {"negative", "mixed"}
    ]
    source_counts = Counter(record["source"] for record in included)
    source_group_counts = Counter(record["source_group"] for record in included)
    sentiment_counts = Counter(
        str(record["classification"].get("overall_sentiment") or "unclassified")
        for record in independent
    )
    rating_counts = Counter(
        str(int(float(record["rating"]))) if record.get("rating") is not None else "missing"
        for record in independent
    )
    praise = count_labels(positive_records, "praise_drivers")
    failures = count_labels(negative_records, "failure_modes")
    stages = count_labels(independent_classified, "journey_stages")
    roles = count_labels(independent_classified, "staff_roles_mentioned")
    actionability = count_labels(independent_classified, "actionability")
    owners = count_labels(independent_classified, "operational_owners")
    positive_themes, _ = theme_counts(positive_records)
    _, negative_themes = theme_counts(negative_records)

    process_outcome: Counter[tuple[str, str]] = Counter()
    for record in independent_classified:
        process = str(record["classification"].get("process_satisfaction") or "unknown")
        outcome = str(record["classification"].get("outcome_satisfaction") or "unknown")
        process_outcome[(process, outcome)] += 1

    denominator = len(independent_classified)
    firm_count = len({record["firm_id"] for record in independent_classified})
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "classification_version": CLASSIFICATION_VERSION,
        "snapshot_at": snapshot_at.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_distinct_reviews": TARGET,
        "gate_met": len(included) >= TARGET,
        "corpus": {
            **load_stats,
            "distinct_before_republication_exclusion": len(records),
            "cross_source_republications_excluded": sum(record["cross_source_republication"] for record in records),
            "included_distinct_reviews": len(included),
            "included_firms": len({record["firm_id"] for record in included}),
            "independent_reviews": len(independent),
            "independent_firms": len({record["firm_id"] for record in independent}),
            "classified_reviews": len(classified),
            "unclassified_reviews": len(included) - len(classified),
            "source_groups": dict(source_group_counts),
            "source_distribution": dict(source_counts),
        },
        "primary_denominator": {
            "description": "Distinct independent-source reviews with pi_reviews_v1 classifications",
            "reviews": denominator,
            "firms": firm_count,
        },
        "sentiment_band_denominators": {
            "positive_reviews": len(positive_records),
            "negative_or_mixed_reviews": len(negative_records),
        },
        "sentiment_distribution": dict(sentiment_counts),
        "rating_distribution": dict(rating_counts),
        "praise_drivers": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, len(positive_records))}
            for key, count in praise.most_common()
        ],
        "failure_modes": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, len(negative_records))}
            for key, count in failures.most_common()
        ],
        "positive_themes": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, len(positive_records))}
            for key, count in positive_themes.most_common()
        ],
        "negative_themes": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, len(negative_records))}
            for key, count in negative_themes.most_common()
        ],
        "journey_stages": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, denominator)}
            for key, count in stages.most_common()
        ],
        "staff_roles": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, denominator)}
            for key, count in roles.most_common()
        ],
        "actionability": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, denominator)}
            for key, count in actionability.most_common()
        ],
        "operational_owners": [
            {"key": key, "label": label(key), "count": count, "percent": pct(count, denominator)}
            for key, count in owners.most_common()
        ],
        "process_outcome_matrix": [
            {"process_satisfaction": process, "outcome_satisfaction": outcome, "count": count, "percent": pct(count, denominator)}
            for (process, outcome), count in sorted(process_outcome.items())
        ],
        "firm_balanced": {
            "praise_drivers": firm_balanced(positive_records, list_field_extractor("praise_drivers")),
            "failure_modes": firm_balanced(negative_records, list_field_extractor("failure_modes")),
            "journey_stages": firm_balanced(independent_classified, list_field_extractor("journey_stages")),
        },
        "limitations": [
            "Public reviews are self-selected and do not represent every client experience.",
            "Google supplies most records; Yelp and several other sources are underrepresented.",
            "The current classification version is primarily a deterministic rules baseline and may miss implicit themes.",
            "Associations describe what reviewers mention; they do not establish causation.",
            "Firm size, case outcome, staff role, and journey stage are reported only when the review or classification explicitly supports them.",
        ],
    }
    return result


def export(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "aggregate.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    corpus = result["corpus"]
    independent_n = result["primary_denominator"]["reviews"]
    charts = output_dir / "charts"
    write_csv(charts / "01_source_composition.csv", [
        {"source": source, "count": count, "percent_of_included": pct(count, corpus["included_distinct_reviews"])}
        for source, count in corpus["source_distribution"].items()
    ])
    write_csv(charts / "02_sentiment_distribution.csv", [
        {"sentiment": key, "count": count, "percent": pct(count, independent_n)}
        for key, count in result["sentiment_distribution"].items()
    ])
    write_csv(charts / "03_praise_and_failures.csv", [
        {"type": kind, **row} for kind, rows in (
            ("praise", result["praise_drivers"]), ("failure", result["failure_modes"]),
        ) for row in rows
    ])
    write_csv(charts / "04_theme_sentiment.csv", [
        {"sentiment": sentiment, **row} for sentiment, rows in (
            ("positive", result["positive_themes"]), ("negative", result["negative_themes"]),
        ) for row in rows
    ])
    write_csv(charts / "05_journey_stages.csv", result["journey_stages"])
    write_csv(charts / "06_process_outcome.csv", result["process_outcome_matrix"])
    write_csv(charts / "07_actionability.csv", result["actionability"])
    firm_rows = []
    for kind, values in result["firm_balanced"].items():
        firm_rows.extend({"type": kind, "key": key, "label": label(key), "firm_balanced_percent": value} for key, value in values.items())
    write_csv(charts / "08_firm_balanced_themes.csv", firm_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-at", required=True, help="UTC ISO timestamp that freezes the corpus")
    parser.add_argument("--output-dir", default="analysis/pi_review_corpus")
    args = parser.parse_args()
    snapshot_at = parse_time(args.snapshot_at)
    if snapshot_at is None:
        raise SystemExit("--snapshot-at must be an ISO timestamp")
    records, load_stats = load_records(snapshot_at)
    result = analyze(records, snapshot_at, load_stats)
    if not result["gate_met"]:
        raise SystemExit(f"hard gate not met: {result['corpus']['included_distinct_reviews']} < {TARGET}")
    if result["corpus"]["unclassified_reviews"]:
        raise SystemExit(f"classification gate not met: {result['corpus']['unclassified_reviews']} unclassified")
    export(result, Path(args.output_dir))
    print(json.dumps({
        "snapshot_at": result["snapshot_at"],
        "included_distinct_reviews": result["corpus"]["included_distinct_reviews"],
        "independent_reviews": result["corpus"]["independent_reviews"],
        "included_firms": result["corpus"]["included_firms"],
        "classified_reviews": result["corpus"]["classified_reviews"],
        "output_dir": args.output_dir,
    }, indent=2))


if __name__ == "__main__":
    main()
