from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from contextlib import closing
from typing import Any

import httpx

from app.manifest import TOOLS


DEFAULT_DB_URL = "https://raw.githubusercontent.com/joshpetit/sda-hymnal/master/data/hymns.db"
SOURCE_REPO_URL = "https://github.com/joshpetit/sda-hymnal"
SOURCE_DB_WEB_URL = f"{SOURCE_REPO_URL}/blob/master/data/hymns.db"


class SourceHTTPError(ValueError):
    def __init__(self, url: str, status_code: int, message: str) -> None:
        super().__init__(f"{url} failed with HTTP {status_code}: {message}")
        self.url = url
        self.status_code = status_code
        self.message = message


def list_tools_for_hub() -> list[dict[str, Any]]:
    return TOOLS


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    arguments = arguments or {}
    if name == "search_hymns":
        return search_hymns(arguments)
    if name == "get_hymn":
        return get_hymn(arguments)
    if name == "get_hymn_lyrics":
        return get_hymn_lyrics(arguments)
    if name == "list_hymnbook_versions":
        return list_hymnbook_versions(arguments)
    if name == "download_hymn":
        return download_hymn(arguments)
    raise ValueError(f"Unknown tool: {name}")


def search_hymns(arguments: dict[str, Any]) -> dict[str, Any]:
    query = _clean(arguments.get("query"))
    number = _optional_int(arguments.get("number"))
    limit = _safe_int(arguments.get("limit"), default=10, minimum=1, maximum=50)
    if not query and not number:
        return _failure("hymn_search", "query or number is required", "validation_error")

    try:
        hymns = _search_rows(query=query, number=number, limit=limit)
    except SourceHTTPError as exc:
        return _failure(
            "hymn_search",
            exc.message,
            "source_http_error",
            upstream_status_code=exc.status_code,
            source_url=exc.url,
        )
    except ValueError as exc:
        return _failure("hymn_search", str(exc), "source_request_failed")

    compact = [_hymn_payload(row, include_lyrics=False) for row in hymns]
    message = _search_message(compact, query or str(number))
    return {
        "kind": "hymn_search",
        "status": "found" if compact else "not_found",
        "success": True,
        "has_results": bool(compact),
        "query": query or None,
        "number": number,
        "count": len(compact),
        "hymns": compact,
        "message": message,
        "content": message,
        "sources": _source_list(_db_url(), SOURCE_REPO_URL),
    }


def get_hymn(arguments: dict[str, Any]) -> dict[str, Any]:
    number = _optional_int(arguments.get("number"))
    title = _clean(arguments.get("title"))
    include_lyrics = bool(arguments.get("include_lyrics", True))
    if not number and not title:
        return _failure("hymn_lookup", "number or title is required", "validation_error")

    try:
        row = _find_hymn(number=number, title=title)
    except SourceHTTPError as exc:
        return _failure(
            "hymn_lookup",
            exc.message,
            "source_http_error",
            upstream_status_code=exc.status_code,
            source_url=exc.url,
        )
    except ValueError as exc:
        return _failure("hymn_lookup", str(exc), "source_request_failed")

    if not row:
        return _not_found("hymn_lookup", f"No SDA Hymnal entry matched {number or title}.")

    hymn = _hymn_payload(row, include_lyrics=include_lyrics)
    message = f"Found hymn {hymn['number']}: {hymn['title']}."
    return {
        "kind": "hymn_lookup",
        "status": "found",
        "success": True,
        "has_results": True,
        "hymn": hymn,
        "message": message,
        "content": hymn.get("lyrics_text") if include_lyrics else message,
        "sources": _source_list(_db_url(), SOURCE_REPO_URL),
    }


def get_hymn_lyrics(arguments: dict[str, Any]) -> dict[str, Any]:
    number = _optional_int(arguments.get("number"))
    if not number:
        return _failure("hymn_lyrics", "number is required", "validation_error")
    result = get_hymn({"number": number, "include_lyrics": True})
    result["kind"] = "hymn_lyrics"
    return result


def list_hymnbook_versions(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        counts = _database_counts()
    except SourceHTTPError as exc:
        return _failure(
            "hymnbook_versions",
            exc.message,
            "source_http_error",
            upstream_status_code=exc.status_code,
            source_url=exc.url,
        )
    except ValueError as exc:
        return _failure("hymnbook_versions", str(exc), "source_request_failed")

    version = {
        "id": "sda-hymnal-github-sqlite",
        "name": "SDA Hymnal SQLite source",
        "source_url": SOURCE_REPO_URL,
        "database_url": _db_url(),
        "hymn_count": counts["hymn_count"],
        "section_count": counts["section_count"],
        "supports_number_search": True,
        "supports_title_search": True,
        "supports_lyrics": True,
        "supports_tunes_audio": False,
        "supports_multiple_hymnbooks": False,
    }
    message = f"Loaded live hymnbook source with {counts['hymn_count']} hymns."
    return {
        "kind": "hymnbook_versions",
        "status": "found",
        "success": True,
        "has_results": True,
        "versions": [version],
        "future_capabilities": ["tunes_audio", "additional_hymnbook_versions"],
        "message": message,
        "content": message,
        "sources": _source_list(_db_url(), SOURCE_REPO_URL),
    }


def download_hymn(arguments: dict[str, Any]) -> dict[str, Any]:
    number = _optional_int(arguments.get("number"))
    requested_format = (_clean(arguments.get("format")) or "web").lower()
    if not number:
        return _failure("hymn_download", "number is required", "validation_error")
    if requested_format not in {"web", "json", "database", "all"}:
        return _failure("hymn_download", "format must be web, json, database, or all", "validation_error")

    lookup = get_hymn({"number": number, "include_lyrics": True})
    if lookup.get("status") != "found":
        lookup["kind"] = "hymn_download"
        return lookup

    links = {
        "web": SOURCE_REPO_URL,
        "database": _db_url(),
        "json": SOURCE_DB_WEB_URL,
    }
    selected = links if requested_format == "all" else {requested_format: links.get(requested_format)}
    selected = {key: value for key, value in selected.items() if value}
    message = f"Found live source links for hymn {number}."
    return {
        "kind": "hymn_download",
        "status": "found",
        "success": True,
        "has_results": True,
        "hymn": lookup["hymn"],
        "format": requested_format,
        "links": selected,
        "message": message,
        "content": message,
        "sources": _source_list(*selected.values()),
    }


def _search_rows(*, query: str, number: int | None, limit: int) -> list[sqlite3.Row]:
    if number:
        row = _find_hymn(number=number, title="")
        return [row] if row else []
    like = f"%{query}%"
    sql = """
        SELECT h.*, s.Title AS section_title
        FROM Hymns h
        LEFT JOIN Sections s ON h.section = s._id
        WHERE h.title LIKE ?
           OR h.refrain LIKE ?
           OR h.refrain2 LIKE ?
           OR h.verse1 LIKE ?
           OR h.verse2 LIKE ?
           OR h.verse3 LIKE ?
           OR h.verse4 LIKE ?
           OR h.verse5 LIKE ?
           OR h.verse6 LIKE ?
           OR h.verse7 LIKE ?
           OR s.Title LIKE ?
        ORDER BY
            CASE WHEN h.title LIKE ? THEN 0 ELSE 1 END,
            h.number ASC
        LIMIT ?
    """
    with closing(_db_connection()) as conn:
        conn.row_factory = sqlite3.Row
        return list(conn.execute(sql, [like] * 11 + [like, limit]).fetchall())


def _find_hymn(*, number: int | None, title: str) -> sqlite3.Row | None:
    with closing(_db_connection()) as conn:
        conn.row_factory = sqlite3.Row
        if number:
            return conn.execute(
                """
                SELECT h.*, s.Title AS section_title
                FROM Hymns h
                LEFT JOIN Sections s ON h.section = s._id
                WHERE h.number = ?
                LIMIT 1
                """,
                (number,),
            ).fetchone()
        like = f"%{title}%"
        return conn.execute(
            """
            SELECT h.*, s.Title AS section_title
            FROM Hymns h
            LEFT JOIN Sections s ON h.section = s._id
            WHERE h.title LIKE ?
            ORDER BY CASE WHEN h.title = ? THEN 0 ELSE 1 END, h.number ASC
            LIMIT 1
            """,
            (like, title),
        ).fetchone()


def _database_counts() -> dict[str, int]:
    with closing(_db_connection()) as conn:
        hymn_count = conn.execute("SELECT COUNT(*) FROM Hymns").fetchone()[0]
        section_count = conn.execute("SELECT COUNT(*) FROM Sections").fetchone()[0]
    return {"hymn_count": int(hymn_count), "section_count": int(section_count)}


def _db_connection() -> sqlite3.Connection:
    payload = _download_db_bytes()
    conn = sqlite3.connect(":memory:")
    try:
        conn.deserialize(payload)
        return conn
    except AttributeError:
        conn.close()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise ValueError(f"Downloaded hymnal database is invalid: {exc}") from exc

    with tempfile.NamedTemporaryFile(suffix=".db") as handle:
        handle.write(payload)
        handle.flush()
        disk_conn = sqlite3.connect(handle.name)
        memory_conn = sqlite3.connect(":memory:")
        disk_conn.backup(memory_conn)
        disk_conn.close()
        return memory_conn


def _download_db_bytes() -> bytes:
    url = _db_url()
    with _http_client() as client:
        response = client.get(url)
    if response.status_code >= 400:
        raise SourceHTTPError(url, response.status_code, _clip(response.text, 200))
    return response.content


def _http_client() -> httpx.Client:
    return httpx.Client(
        timeout=_request_timeout(),
        follow_redirects=True,
        headers={
            "Accept": "application/octet-stream,application/vnd.github.raw,*/*",
            "User-Agent": "sda-hymnbook-mcp/0.1 (+https://sda-hymnbook.marona.ai)",
        },
    )


def _hymn_payload(row: sqlite3.Row, *, include_lyrics: bool) -> dict[str, Any]:
    verses = [
        {"number": index, "text": _clean(row[f"verse{index}"])}
        for index in range(1, 8)
        if _clean(row[f"verse{index}"])
    ]
    refrain = _clean(row["refrain"])
    refrain2 = _clean(row["refrain2"])
    payload: dict[str, Any] = {
        "number": int(row["number"]),
        "title": _clean(row["title"]),
        "section": _clean(row["section_title"]),
        "source": "joshpetit/sda-hymnal data/hymns.db",
        "source_url": SOURCE_REPO_URL,
        "database_url": _db_url(),
        "audio_available": False,
        "tune_available": False,
    }
    if include_lyrics:
        payload["refrain"] = refrain or None
        payload["refrain2"] = refrain2 or None
        payload["verses"] = verses
        payload["lyrics_text"] = _lyrics_text(payload)
    return payload


def _lyrics_text(hymn: dict[str, Any]) -> str:
    parts = [f"{hymn['number']}. {hymn['title']}"]
    for verse in hymn.get("verses", []):
        parts.append(f"{verse['number']}. {verse['text']}")
    if hymn.get("refrain"):
        parts.append(f"Refrain: {hymn['refrain']}")
    if hymn.get("refrain2"):
        parts.append(f"Second refrain: {hymn['refrain2']}")
    return "\n\n".join(parts)


def _search_message(hymns: list[dict[str, Any]], query: str) -> str:
    if not hymns:
        return f"No live SDA Hymnal results matched '{query}'."
    titles = ", ".join(f"{hymn['number']} {hymn['title']}" for hymn in hymns[:3])
    return f"Found {len(hymns)} live hymn result(s) for '{query}': {titles}."


def _db_url() -> str:
    return os.getenv("SDA_HYMNBOOK_DB_URL", DEFAULT_DB_URL).strip() or DEFAULT_DB_URL


def _request_timeout() -> float:
    value = os.getenv("SDA_HYMNBOOK_HTTP_TIMEOUT_SECONDS", "30")
    try:
        return max(1.0, float(value))
    except ValueError:
        return 30.0


def _not_found(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "not_found",
        "success": True,
        "has_results": False,
        "message": message,
        "content": message,
        **extra,
    }


def _failure(kind: str, message: str, error_code: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "failed",
        "success": False,
        "has_results": False,
        "message": message,
        "content": message,
        "error": {"code": error_code, **{k: v for k, v in extra.items() if k.startswith("upstream_")}},
        **{k: v for k, v in extra.items() if not k.startswith("upstream_")},
    }


def _source_list(*urls: str | None) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen:
            continue
        sources.append({"url": url})
        seen.add(url)
    return sources


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _clip(value: str, limit: int) -> str:
    value = _clean(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."


def _safe_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
