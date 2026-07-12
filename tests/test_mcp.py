import atexit
import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app(), base_url="http://127.0.0.1:8000")
client.__enter__()
atexit.register(lambda: client.__exit__(None, None, None))


def rpc(method: str, params: dict | None = None, request_id: int = 1):
    if method == "initialize" and params is None:
        params = {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "sda-hymnbook-test", "version": "0.1.0"},
        }
    response = client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "X-Marona-Identity-Subject": "usr_test",
            "X-Marona-Identity-Trust": "verified",
            "X-Marona-Session-Id": "session_test",
            "X-Marona-Interface": "api",
        },
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
    )
    assert response.status_code == 200
    return response.json()


def assert_standard_result(structured: dict) -> None:
    for field in ("status", "success", "message", "content", "content_type", "presentation_hint", "context"):
        assert field in structured
    assert isinstance(structured["content"], str)
    assert isinstance(structured["context"], str)


def hymnal_db_bytes() -> bytes:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE Sections (_id INTEGER PRIMARY KEY, Title TEXT, FirstHymn INTEGER, LastHymn INTEGER);
        CREATE TABLE Hymns (
            _id INTEGER PRIMARY KEY,
            number INTEGER,
            title TEXT,
            refrain TEXT,
            refrain2 TEXT,
            verse1 TEXT,
            verse2 TEXT,
            verse3 TEXT,
            verse4 TEXT,
            verse5 TEXT,
            verse6 TEXT,
            verse7 TEXT,
            section INTEGER,
            subsection INTEGER
        );
        INSERT INTO Sections VALUES (1, 'Worship', 1, 10);
        INSERT INTO Hymns VALUES (
            1, 1, 'Praise to the Lord', '', '',
            'Praise to the Lord, the Almighty, the King of creation!',
            'Praise to the Lord, who o er all things so wondrously reigneth',
            '', '', '', '', '', 1, NULL
        );
        """
    )
    data = conn.serialize()
    conn.close()
    return data


def fake_storage_hymnbook_catalog():
    return {
        "items": [
            {
                "id": "hymnbook:en:HT1888",
                "provider": "adventist-archives",
                "collection": "sda-hymnal",
                "item_type": "hymnbook",
                "code": "HT1888",
                "title": "Hymns and Tunes",
                "language": "en",
                "format": "pdf",
                "storage_path": "hymnbooks/sda-hymnal/en/pdf/HT1888.pdf",
                "download_path": "/downloads/hymnbooks/sda-hymnal/en/pdf/HT1888.pdf",
                "aliases": ["HT1888", "Hymns and Tunes"],
                "bytes": 1234,
                "sha256": "abc",
                "source_url": "https://documents.adventistarchives.org/Books/HT1888.pdf",
                "official_archive_id": "HT1888",
            }
        ]
    }


def test_health_and_manifest() -> None:
    assert client.get("/health").json()["status"] == "ok"
    payload = client.get("/hub-registration").json()
    assert payload["slug"] == "sda-hymnbook"
    assert "search_hymns" in {tool["name"] for tool in payload["tools"]}


def test_initialize_and_tools_list() -> None:
    initialized = rpc("initialize")
    assert initialized["result"]["protocolVersion"] == "2025-03-26"
    tools = rpc("tools/list")
    assert "get_hymn_lyrics" in {tool["name"] for tool in tools["result"]["tools"]}
    assert "search_hymnbooks" in {tool["name"] for tool in tools["result"]["tools"]}


def test_search_hymns_queries_live_db_shape(monkeypatch) -> None:
    monkeypatch.setattr("app.tools._download_db_bytes", hymnal_db_bytes)
    result = rpc(
        "tools/call",
        {"name": "search_hymns", "arguments": {"query": "lord"}},
    )
    structured = result["result"]["structuredContent"]
    assert_standard_result(structured)
    assert structured["status"] == "found"
    assert structured["hymns"][0]["number"] == 1
    assert structured["hymns"][0]["title"] == "Praise to the Lord"


def test_get_hymn_lyrics(monkeypatch) -> None:
    monkeypatch.setattr("app.tools._download_db_bytes", hymnal_db_bytes)
    result = rpc(
        "tools/call",
        {"name": "get_hymn_lyrics", "arguments": {"number": 1}},
    )
    structured = result["result"]["structuredContent"]
    assert_standard_result(structured)
    assert structured["status"] == "found"
    assert "Praise to the Lord" in structured["hymn"]["lyrics_text"]


def test_get_hymn_lyrics_accepts_natural_number_query(monkeypatch) -> None:
    monkeypatch.setattr("app.tools._download_db_bytes", hymnal_db_bytes)
    result = rpc(
        "tools/call",
        {"name": "get_hymn_lyrics", "arguments": {"query": "hymn number 1"}},
    )
    structured = result["result"]["structuredContent"]
    assert_standard_result(structured)
    assert structured["status"] == "found"
    assert structured["hymn"]["number"] == 1
    assert structured["presentation_hint"] == "song"


def test_list_versions_counts_live_db(monkeypatch) -> None:
    monkeypatch.setattr("app.tools._download_db_bytes", hymnal_db_bytes)
    result = rpc("tools/call", {"name": "list_hymnbook_versions", "arguments": {}})
    structured = result["result"]["structuredContent"]
    assert_standard_result(structured)
    assert structured["versions"][0]["hymn_count"] == 1
    assert structured["versions"][0]["section_count"] == 1


def test_download_hymnbook_returns_storage_pdf(monkeypatch) -> None:
    monkeypatch.setattr("app.tools._storage_hymnbook_catalog", fake_storage_hymnbook_catalog)
    result = rpc(
        "tools/call",
        {
            "name": "download_hymnbook",
            "arguments": {"query": "Hymns and Tunes", "language": "en", "format": "pdf"},
        },
    )
    structured = result["result"]["structuredContent"]
    assert_standard_result(structured)
    assert structured["status"] == "found"
    assert structured["content_type"] == "document"
    assert structured["presentation_hint"] == "download"
    assert structured["format"] == "pdf"
    assert structured["download_url"] == "https://sda-library.marona.ai/downloads/hymnbooks/sda-hymnal/en/pdf/HT1888.pdf"
    assert structured["files"][0]["code"] == "HT1888"
    assert structured["files"][0]["mime_type"] == "application/pdf"


def test_search_hymnbooks_prefers_semantic_index(monkeypatch) -> None:
    captured = {}

    def fake_semantic_search_hymnbooks(**kwargs):
        captured.update(kwargs)
        return {
            "kind": "hymnbook_search",
            "status": "found",
            "success": True,
            "has_results": True,
            "query": kwargs["query"],
            "language": kwargs["language"],
            "search_mode": "hybrid_semantic",
            "count": 1,
            "results": [
                {
                    "code": "HT1888",
                    "title": "Hymns and Tunes",
                    "download_url": "https://sda-library.marona.ai/downloads/hymnbooks/sda-hymnal/en/pdf/HT1888.pdf",
                    "snippet": "Holy, holy, holy.",
                }
            ],
            "hymnbooks": [],
            "message": "Found semantic result.",
            "content": "Found semantic result.",
        }

    monkeypatch.setattr("app.tools._semantic_search_hymnbooks", fake_semantic_search_hymnbooks)
    result = rpc(
        "tools/call",
        {
            "name": "search_hymnbooks",
            "arguments": {"query": "holy holy holy", "language": "en", "limit": 3},
        },
    )
    structured = result["result"]["structuredContent"]
    assert_standard_result(structured)
    assert structured["status"] == "found"
    assert structured["search_mode"] == "hybrid_semantic"
    assert structured["results"][0]["code"] == "HT1888"
    assert captured["query"] == "holy holy holy"
    assert captured["limit"] == 3


def test_search_validation_returns_tool_failure() -> None:
    result = rpc("tools/call", {"name": "search_hymns", "arguments": {}})
    structured = result["result"]["structuredContent"]
    assert_standard_result(structured)
    assert structured["status"] == "failed"
    assert structured["success"] is False
    assert structured["content_type"] == "error"
