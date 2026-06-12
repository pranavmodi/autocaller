import json
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.front import router as front_router
from app.services import competitor_graph
from app.services.competitor_graph import (
    build_competitor_graph_from_cache,
    case_mix_cosine,
    case_mix_for_texts,
    extract_dollar_amounts,
    parse_first_address,
    value_tier_for_amounts,
)


def test_address_parsing_real_shaped_fixtures():
    parsed = parse_first_address(
        json.dumps([
            "8383 Wilshire Boulevard, Suite 945, Beverly Hills, California 90211",
            "123 Other St, Austin, TX 78704",
        ])
    )
    assert parsed.city == "Beverly Hills"
    assert parsed.state == "CA"
    assert parsed.metro == "los-angeles"

    loose = parse_first_address(json.dumps(["6310 San Vicente Blvd. Suite 401 Los Angeles, CA 90048"]))
    assert loose.city == "Los Angeles"
    assert loose.metro == "los-angeles"

    fallback = parse_first_address(json.dumps(["2512 S. Interstate 35, Ste. 350, Austin, TX 78704"]))
    assert fallback.state == "TX"
    assert fallback.metro == "state:TX"

    missing = parse_first_address("[]")
    assert missing.city is None
    assert missing.metro is None


def test_case_mix_amounts_and_cosine():
    mix_a = case_mix_for_texts([
        "Commercial MVA rear-end collision with lien at $12,500",
        "Slip and fall premises claim with bill of $4,200",
    ])
    mix_b = case_mix_for_texts(["Auto accident and truck accident bills $15,000"])

    assert mix_a["mva"] == 0.5
    assert mix_a["premises"] == 0.5
    assert case_mix_cosine(mix_a, mix_b) > 0.65
    assert extract_dollar_amounts("ignore $75 but keep $4,200 and $15000") == [4200.0, 15000.0]
    assert value_tier_for_amounts([4200.0, 15000.0, 30000.0])[0] == "mid"
    assert value_tier_for_amounts([30000.0])[0] == "large"


def _seed_cache(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE pif_firms (
            id TEXT PRIMARY KEY,
            firm_name TEXT NOT NULL,
            website TEXT,
            emails TEXT DEFAULT '[]',
            addresses TEXT DEFAULT '[]',
            conversation_ids TEXT DEFAULT '[]'
        );
        CREATE TABLE front_conversations (
            id TEXT PRIMARY KEY,
            subject TEXT
        );
        CREATE TABLE front_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            author_email TEXT,
            body_text TEXT
        );
        """
    )
    firms = [
        (
            "pif-a",
            "Alpha Injury Law",
            "https://alphainjury.example",
            json.dumps(["intake@alphainjury.example"]),
            json.dumps(["100 Wilshire Blvd, Los Angeles, CA 90017"]),
            json.dumps(["c1", "c4"]),
        ),
        (
            "pif-b",
            "Beta Accident Group",
            "https://betaaccident.example",
            json.dumps(["records@betaaccident.example"]),
            json.dumps(["200 Ocean Ave, Santa Monica, CA 90401"]),
            json.dumps(["c2", "c4"]),
        ),
        (
            "pif-c",
            "Central Workers Firm",
            "https://centralworkers.example",
            json.dumps(["hello@centralworkers.example"]),
            json.dumps(["300 Main St, Fresno, CA 93711"]),
            json.dumps(["c3"]),
        ),
    ]
    conn.executemany("INSERT INTO pif_firms VALUES (?, ?, ?, ?, ?, ?)", firms)
    conversations = [
        ("c1", "Alpha auto accident lien"),
        ("c2", "Beta truck accident bill"),
        ("c3", "Work injury claim"),
        ("c4", "Substitution of attorney notice"),
    ]
    conn.executemany("INSERT INTO front_conversations VALUES (?, ?)", conversations)
    messages = [
        ("m1", "c1", "intake@alphainjury.example", "Motor vehicle accident lien is $12,000."),
        ("m2", "c2", "records@betaaccident.example", "Truck accident bill is $14,000."),
        ("m3", "c3", "hello@centralworkers.example", "Workers compensation injury bill is $3,000."),
        (
            "m4",
            "c4",
            "intake@alphainjury.example",
            "Substitution of attorney: Alpha Injury Law no longer represents this client. New counsel is Beta Accident Group.",
        ),
    ]
    conn.executemany("INSERT INTO front_messages VALUES (?, ?, ?, ?)", messages)
    conn.commit()
    conn.close()


def test_graph_build_top_k_uniqueness_and_switching_probe(tmp_path):
    db_path = tmp_path / "mission.db"
    _seed_cache(db_path)

    graph = build_competitor_graph_from_cache(
        mission_db_path=db_path,
        front_activities=[
            {"pif_id": "pif-a", "domain": "alphainjury.example", "last_seen_at": datetime.now(timezone.utc)},
            {"pif_id": "pif-b", "domain": "betaaccident.example", "last_seen_at": datetime.now(timezone.utc)},
        ],
        now=datetime.now(timezone.utc),
    )

    assert graph["firms_with_metro"] == 3
    assert graph["firms_with_case_mix"] == 3
    assert graph["client_switching_hit_count"] >= 1
    assert graph["edges"]
    pairs = {(edge["firm_a_pif_id"], edge["firm_b_pif_id"]) for edge in graph["edges"]}
    assert all(a < b for a, b in pairs)
    assert len(pairs) == len(graph["edges"])
    best = graph["edges"][0]
    assert {best["firm_a_pif_id"], best["firm_b_pif_id"]} == {"pif-a", "pif-b"}
    assert best["score"] >= 0.65
    assert "substitution" in json.dumps(best["evidence"]).lower()


def test_front_competitor_api_smoke(monkeypatch):
    app = FastAPI()
    app.include_router(front_router)

    async def fake_rebuild():
        return {"firms_with_features": 2, "edge_count": 1, "duration_seconds": 0.01}

    async def fake_summary():
        return {
            "firms_with_features": 2,
            "firms_with_metro": 2,
            "edge_count": 1,
            "last_computed_at": "2026-06-12T00:00:00+00:00",
            "metro_counts": [{"metro": "los-angeles", "count": 2}],
            "tier_distribution": {"mid": 2},
        }

    async def fake_get(domain="", pif_id="", limit=10):
        return {
            "firm": {"pif_id": pif_id or "pif-a", "firm_name": "Alpha Injury Law", "domain": domain or None},
            "competitors": [{"pif_id": "pif-b", "firm_name": "Beta Accident Group", "score": 0.8}],
        }

    monkeypatch.setattr("app.api.front.rebuild_competitor_graph", fake_rebuild)
    monkeypatch.setattr("app.api.front.competitor_summary", fake_summary)
    monkeypatch.setattr("app.api.front.get_competitors", fake_get)

    client = TestClient(app)
    assert client.post("/api/front/competitors/rebuild").json()["edge_count"] == 1
    assert client.get("/api/front/competitors/summary").json()["firms_with_metro"] == 2
    assert client.get("/api/front/competitors?pif_id=pif-a").json()["competitors"][0]["score"] == 0.8
    assert client.get("/api/front/competitors").status_code == 400
