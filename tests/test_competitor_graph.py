import json
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.front import router as front_router
from app.db.models import CompetitorEdgeRow, FirmCompetitiveFeatureRow, FrontFirmActivityRow
from app.services import competitor_graph
from app.services.competitor_graph import (
    build_competitor_graph_from_cache,
    case_mix_cosine,
    case_mix_for_texts,
    extract_dollar_amounts,
    parse_first_address,
    value_tier_for_amounts,
)


class _OrmResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _CompetitorOrmSession:
    def __init__(self, *, features, edges, activities):
        self.features = list(features)
        self.edges = list(edges)
        self.activities = list(activities)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, model, key):
        if model is FirmCompetitiveFeatureRow:
            return next((row for row in self.features if row.pif_id == key), None)
        return None

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        params = stmt.compile().params
        text = str(stmt)
        if entity is FirmCompetitiveFeatureRow:
            ids = _param_strings(params)
            if ids:
                return _OrmResult([row for row in self.features if row.pif_id in ids])
            needle = next((str(value).strip("%").lower() for value in params.values() if isinstance(value, str) and "%" in value), "")
            rows = [
                row for row in self.features
                if needle in row.firm_name.lower() or needle in (row.domain or "").lower()
            ]
            rows.sort(key=lambda row: row.firm_name)
            return _OrmResult(rows[: int(params.get("param_1") or 50)])
        if entity is CompetitorEdgeRow:
            ids = set(_param_strings(params))
            if " AND " in text and ids:
                rows = [row for row in self.edges if row.firm_a_pif_id in ids and row.firm_b_pif_id in ids]
            elif ids:
                rows = [row for row in self.edges if row.firm_a_pif_id in ids or row.firm_b_pif_id in ids]
            else:
                rows = list(self.edges)
            rows.sort(key=lambda row: row.score, reverse=True)
            return _OrmResult(rows)
        if entity is FrontFirmActivityRow:
            strings = set(_param_strings(params))
            return _OrmResult([
                row for row in self.activities
                if (row.pif_id and row.pif_id in strings) or row.domain in strings
            ])
        return _OrmResult([])


def _param_strings(params):
    values = []
    for value in params.values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
    return [value for value in values if "%" not in value]


def _feature(pif_id, name, domain, *, metro="los-angeles", value_tier="mid", volume_proxy=4):
    return FirmCompetitiveFeatureRow(
        pif_id=pif_id,
        firm_name=name,
        domain=domain,
        metro=metro,
        city="Los Angeles",
        state="CA",
        case_mix={"mva": 1.0},
        value_tier=value_tier,
        volume_proxy=volume_proxy,
        evidence={},
    )


def _edge(a, b, score, *, why="same metro; case mix similarity 1.00"):
    first, second = sorted((a, b))
    return CompetitorEdgeRow(
        id=f"edge-{first}-{second}",
        firm_a_pif_id=first,
        firm_b_pif_id=second,
        metro="los-angeles",
        score=score,
        components={"geo": 1.0, "case_mix": score},
        evidence={"why": why},
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


def _create_cache(path, firms, conversations=(), messages=()):
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
    conn.executemany("INSERT INTO pif_firms VALUES (?, ?, ?, ?, ?, ?)", firms)
    conn.executemany("INSERT INTO front_conversations VALUES (?, ?)", conversations)
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


def test_graph_build_excludes_obvious_non_law_vendors(tmp_path):
    db_path = tmp_path / "mission.db"
    _create_cache(
        db_path,
        [
            (
                "pif-law",
                "Alpha Injury Law",
                "https://alphainjury.example",
                json.dumps(["intake@alphainjury.example"]),
                json.dumps(["100 Wilshire Blvd, Los Angeles, CA 90017"]),
                json.dumps(["c1"]),
            ),
            (
                "pif-vendor",
                "Precise Imaging",
                "https://precisemri.example",
                json.dumps(["records@precisemri.example"]),
                json.dumps(["200 Wilshire Blvd, Los Angeles, CA 90017"]),
                json.dumps(["c2"]),
            ),
        ],
        conversations=[
            ("c1", "Auto accident lien"),
            ("c2", "MRI bill"),
        ],
        messages=[
            ("m1", "c1", "intake@alphainjury.example", "Motor vehicle accident lien is $12,000."),
            ("m2", "c2", "records@precisemri.example", "MRI bill is $12,000."),
        ],
    )

    graph = build_competitor_graph_from_cache(mission_db_path=db_path)

    assert graph["excluded_non_competitor_count"] == 1
    assert {feature["pif_id"] for feature in graph["features"]} == {"pif-law"}
    assert graph["edges"] == []


def test_graph_build_does_not_connect_sparse_other_only_firms(tmp_path):
    db_path = tmp_path / "mission.db"
    _create_cache(
        db_path,
        [
            (
                "pif-a",
                "Alpha Law",
                "https://alphalaw.example",
                json.dumps(["hello@alphalaw.example"]),
                json.dumps(["100 Wilshire Blvd, Los Angeles, CA 90017"]),
                json.dumps([]),
            ),
            (
                "pif-b",
                "Beta Law",
                "https://betalaw.example",
                json.dumps(["hello@betalaw.example"]),
                json.dumps(["200 Wilshire Blvd, Los Angeles, CA 90017"]),
                json.dumps([]),
            ),
        ],
    )

    graph = build_competitor_graph_from_cache(mission_db_path=db_path)

    assert len(graph["features"]) == 2
    assert graph["firms_with_case_mix"] == 0
    assert graph["edges"] == []


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


def test_front_competitor_search_api_matches_name_and_domain(monkeypatch):
    app = FastAPI()
    app.include_router(front_router)
    features = [
        _feature("pif-a", "Alpha Injury Law", "alphainjury.example"),
        _feature("pif-b", "Beta Accident Group", "betapi.example"),
        _feature("pif-c", "Central Workers Firm", "centralworkers.example", metro="central-valley"),
    ]
    edges = [_edge("pif-a", "pif-b", 0.8), _edge("pif-a", "pif-c", 0.3)]
    activities = [FrontFirmActivityRow(domain="alphainjury.example", pif_id="pif-a", warm_score=210)]
    session = _CompetitorOrmSession(features=features, edges=edges, activities=activities)
    monkeypatch.setattr(competitor_graph, "AsyncSessionLocal", lambda: session)

    client = TestClient(app)
    assert client.get("/api/front/competitors/search?q=a").status_code == 400
    name_rows = client.get("/api/front/competitors/search?q=alpha").json()["results"]
    assert name_rows[0]["pif_id"] == "pif-a"
    assert name_rows[0]["edge_count"] == 2
    assert name_rows[0]["is_warm_list"] is True
    domain_rows = client.get("/api/front/competitors/search?q=betapi").json()["results"]
    assert domain_rows[0]["pif_id"] == "pif-b"


def test_front_competitor_graph_api_includes_neighbor_edges_and_404(monkeypatch):
    app = FastAPI()
    app.include_router(front_router)
    features = [
        _feature("pif-a", "Alpha Injury Law", "alphainjury.example", volume_proxy=9),
        _feature("pif-b", "Beta Accident Group", "beta.example", volume_proxy=4),
        _feature("pif-c", "Coastal Trial Firm", "coastal.example", volume_proxy=1),
    ]
    edges = [
        _edge("pif-a", "pif-b", 0.9, why="alpha beta evidence"),
        _edge("pif-a", "pif-c", 0.8, why="alpha coastal evidence"),
        _edge("pif-b", "pif-c", 0.7, why="neighbor edge evidence"),
    ]
    session = _CompetitorOrmSession(features=features, edges=edges, activities=[])
    monkeypatch.setattr(competitor_graph, "AsyncSessionLocal", lambda: session)

    client = TestClient(app)
    payload = client.get("/api/front/competitors/graph?pif_id=pif-a&depth=1").json()
    assert {node["pif_id"] for node in payload["nodes"]} == {"pif-a", "pif-b", "pif-c"}
    assert any({link["source"], link["target"]} == {"pif-b", "pif-c"} for link in payload["links"])
    assert any(link["evidence_summary"] == "neighbor edge evidence" for link in payload["links"])
    assert client.get("/api/front/competitors/graph?pif_id=missing").status_code == 404


def test_front_competitor_graph_api_depth_two_caps_nodes(monkeypatch):
    app = FastAPI()
    app.include_router(front_router)
    features = [_feature("pif-center", "Center Firm", "center.example")]
    edges = []
    for index in range(70):
        pif_id = f"pif-{index:02d}"
        features.append(_feature(pif_id, f"Firm {index:02d}", f"firm{index:02d}.example", volume_proxy=index + 1))
        edges.append(_edge("pif-center", pif_id, 1.0 - (index / 100)))
    session = _CompetitorOrmSession(features=features, edges=edges, activities=[])
    monkeypatch.setattr(competitor_graph, "AsyncSessionLocal", lambda: session)

    client = TestClient(app)
    payload = client.get("/api/front/competitors/graph?pif_id=pif-center&depth=2").json()
    assert len(payload["nodes"]) == 60
    assert payload["nodes"][0]["pif_id"] == "pif-center"
    assert "pif-00" in {node["pif_id"] for node in payload["nodes"]}
    assert "pif-69" not in {node["pif_id"] for node in payload["nodes"]}
