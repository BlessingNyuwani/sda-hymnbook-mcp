from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from contextlib import closing
from functools import lru_cache
from typing import Any

import httpx

from app.manifest import TOOLS


DEFAULT_DB_URL = "https://raw.githubusercontent.com/joshpetit/sda-hymnal/master/data/hymns.db"
SOURCE_REPO_URL = "https://github.com/joshpetit/sda-hymnal"
SOURCE_DB_WEB_URL = f"{SOURCE_REPO_URL}/blob/master/data/hymns.db"
SDA_LIBRARY_DEFAULT_BASE_URL = "https://sda-library.marona.ai"
SDA_LIBRARY_HYMNBOOK_CATALOG_PATH = "/catalog/hymnbooks.json"


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
    if name == "search_hymnbooks":
        return search_hymnbooks(arguments)
    if name == "get_hymn":
        return get_hymn(arguments)
    if name == "get_hymn_lyrics":
        return get_hymn_lyrics(arguments)
    if name == "list_hymnbook_versions":
        return list_hymnbook_versions(arguments)
    if name == "download_hymn":
        return download_hymn(arguments)
    if name == "download_hymnbook":
        return download_hymnbook(arguments)
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


def search_hymnbooks(arguments: dict[str, Any]) -> dict[str, Any]:
    query = _clean(arguments.get("query"))
    if not query:
        return _failure("hymnbook_search", "query is required", "validation_error")
    language = _language(arguments.get("language"))
    limit = _safe_int(arguments.get("limit"), default=8, minimum=1, maximum=25)

    semantic_result = _semantic_search_hymnbooks(query=query, language=language, limit=limit)
    if semantic_result is not None:
        return semantic_result

    try:
        matches = _storage_hymnbook_matches(query=query, language=language, limit=limit)
    except SourceHTTPError as exc:
        return _failure(
            "hymnbook_search",
            exc.message,
            "source_http_error",
            upstream_status_code=exc.status_code,
            source_url=exc.url,
        )
    except ValueError as exc:
        return _failure("hymnbook_search", str(exc), "source_request_failed")

    results = [_storage_hymnbook_file(item) for item in matches]
    message = _hymnbook_search_message(results, query)
    return {
        "kind": "hymnbook_search",
        "status": "found" if results else "not_found",
        "success": True,
        "has_results": bool(results),
        "query": query,
        "language": language,
        "search_mode": "metadata",
        "count": len(results),
        "results": results,
        "hymnbooks": results,
        "message": message,
        "content": message,
        "sources": _source_list(_storage_hymnbook_catalog_url(), *[result.get("source_url") for result in results]),
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
    result = download_hymnbook(arguments)
    result["kind"] = "hymn_download"
    return result


def download_hymnbook(arguments: dict[str, Any]) -> dict[str, Any]:
    query = _clean(arguments.get("query") or arguments.get("title") or arguments.get("code"))
    language = _language(arguments.get("language"))
    requested_format = (_clean(arguments.get("format")) or "pdf").lower()
    if requested_format not in {"pdf", "all"}:
        return _failure("hymnbook_download", "format must be pdf or all", "validation_error")
    limit = _safe_int(arguments.get("limit"), default=10, minimum=1, maximum=50)

    try:
        matches = _storage_hymnbook_matches(query=query, language=language, limit=limit)
    except SourceHTTPError as exc:
        return _failure(
            "hymnbook_download",
            exc.message,
            "source_http_error",
            upstream_status_code=exc.status_code,
            source_url=exc.url,
        )
    except ValueError as exc:
        return _failure("hymnbook_download", str(exc), "source_request_failed")

    if not matches:
        suffix = f" for '{query}'" if query else ""
        return _not_found("hymnbook_download", f"No SDA Library hymnbook PDFs matched{suffix}.")

    files = [_storage_hymnbook_file(item) for item in matches]
    first_file = files[0]
    message = f"Found {len(files)} SDA Library hymnbook PDF(s)."
    return {
        "kind": "hymnbook_download",
        "status": "found",
        "success": True,
        "has_results": True,
        "query": query or None,
        "language": language,
        "format": "pdf",
        "count": len(files),
        "hymnbooks": files,
        "files": files,
        "links": {"pdf": first_file["url"]},
        "download_urls": [file["url"] for file in files],
        "download_url": first_file["url"],
        "document_url": first_file["url"],
        "filename": first_file["filename"],
        "mime_type": first_file["mime_type"],
        "message": message,
        "content": message,
        "sources": _source_list(_storage_hymnbook_catalog_url(), *[file.get("source_url") for file in files]),
    }


def _semantic_search_hymnbooks(query: str, language: str, limit: int) -> dict[str, Any] | None:
    database_url = (
        os.getenv("SDA_HYMNBOOK_DATABASE_URL")
        or os.getenv("SDA_LIBRARY_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )
    if not database_url or not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        vector = _embed_query(query)
        rows = _hybrid_search_rows(
            database_url,
            query=query,
            language=language,
            vector=vector,
            limit=limit,
            item_type="hymnbook",
        )
    except Exception as exc:
        if _semantic_strict_mode():
            return _failure(
                "hymnbook_search",
                f"Semantic search failed: {_clip(str(exc), 240)}",
                "semantic_search_failed",
                query=query,
            )
        return None

    results = [_hymnbook_semantic_result(row) for row in rows]
    message = _semantic_search_message(results, query, "hymnbook")
    return {
        "kind": "hymnbook_search",
        "status": "found" if results else "not_found",
        "success": True,
        "has_results": bool(results),
        "query": query,
        "language": language,
        "search_mode": "hybrid_semantic",
        "ranking": {
            "strategy": "pgvector_cosine + postgres_full_text + reciprocal_rank_fusion",
            "embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            "embedding_dimensions": _embedding_dimensions(),
        },
        "count": len(results),
        "results": results,
        "hymnbooks": results,
        "message": message,
        "content": message,
        "sources": _source_list(_storage_hymnbook_catalog_url(), *[result.get("source_url") for result in results]),
    }


def _embed_query(query: str) -> list[float]:
    from openai import OpenAI

    client = OpenAI()
    response = client.embeddings.create(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        input=query,
        dimensions=_embedding_dimensions(),
    )
    return list(response.data[0].embedding)


def _hybrid_search_rows(
    database_url: str,
    *,
    query: str,
    language: str,
    vector: list[float],
    limit: int,
    item_type: str,
) -> list[dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    pool_size = max(limit * 8, 40)
    vector_value = _vector_literal(vector)
    params = {
        "query": query,
        "language": language,
        "limit": limit,
        "pool_size": pool_size,
        "vector": vector_value,
        "title_query": f"%{query}%",
        "item_type": item_type,
    }
    filters = """
              AND b.item_type = %(item_type)s
              AND (%(language)s = 'all' OR b.language = %(language)s)
    """
    sql = f"""
        WITH vector_hits AS (
            SELECT
                c.id,
                row_number() OVER (ORDER BY c.embedding <=> %(vector)s::vector) AS vector_rank,
                1 - (c.embedding <=> %(vector)s::vector) AS vector_score
            FROM book_chunks c
            JOIN books b ON b.id = c.book_id
            WHERE c.embedding IS NOT NULL
            {filters}
            ORDER BY c.embedding <=> %(vector)s::vector
            LIMIT %(pool_size)s
        ),
        text_hits AS (
            SELECT
                c.id,
                row_number() OVER (
                    ORDER BY ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', %(query)s)) DESC
                ) AS text_rank,
                ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', %(query)s)) AS text_score
            FROM book_chunks c
            JOIN books b ON b.id = c.book_id
            WHERE c.search_tsv @@ websearch_to_tsquery('english', %(query)s)
            {filters}
            ORDER BY ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', %(query)s)) DESC
            LIMIT %(pool_size)s
        ),
        combined AS (
            SELECT
                coalesce(v.id, t.id) AS chunk_id,
                v.vector_rank,
                v.vector_score,
                t.text_rank,
                t.text_score
            FROM vector_hits v
            FULL OUTER JOIN text_hits t ON t.id = v.id
        )
        SELECT
            b.id AS id,
            b.id AS book_id,
            b.code,
            b.title,
            b.parent_title,
            b.author,
            b.language,
            b.format,
            b.item_type,
            b.collection,
            b.audience,
            b.edition,
            b.download_path,
            b.source_url,
            c.chapter,
            c.page,
            c.text,
            combined.vector_score,
            combined.text_score,
            (
                coalesce(1.0 / (60 + combined.vector_rank), 0) +
                coalesce(1.0 / (60 + combined.text_rank), 0) +
                CASE
                    WHEN lower(b.title) = lower(%(query)s) THEN 0.05
                    WHEN b.title ILIKE %(title_query)s THEN 0.03
                    WHEN b.code ILIKE %(title_query)s THEN 0.025
                    ELSE 0
                END
            ) AS score
        FROM combined
        JOIN book_chunks c ON c.id = combined.chunk_id
        JOIN books b ON b.id = c.book_id
        ORDER BY score DESC, combined.vector_score DESC NULLS LAST
        LIMIT %(limit)s
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        return list(conn.execute(sql, params).fetchall())


def _hymnbook_semantic_result(row: dict[str, Any]) -> dict[str, Any]:
    download_path = row.get("download_path")
    download_url = _storage_download_url(str(download_path)) if download_path else None
    text = _clean(row.get("text"))
    return {
        "id": row.get("id"),
        "book_id": row.get("book_id"),
        "code": row.get("code"),
        "title": row.get("title"),
        "parent_title": row.get("parent_title"),
        "language": row.get("language"),
        "format": row.get("format"),
        "item_type": row.get("item_type"),
        "collection": row.get("collection"),
        "chapter": row.get("chapter"),
        "page": row.get("page"),
        "score": round(float(row.get("score") or 0), 6),
        "vector_score": round(float(row.get("vector_score") or 0), 6) if row.get("vector_score") is not None else None,
        "text_score": round(float(row.get("text_score") or 0), 6) if row.get("text_score") is not None else None,
        "snippet": _snippet(text),
        "download_url": download_url,
        "document_url": download_url,
        "source_url": row.get("source_url"),
    }


def _semantic_search_message(results: list[dict[str, Any]], query: str, label: str) -> str:
    if not results:
        return f"No semantic SDA library {label} results matched '{query}'."
    titles = ", ".join(str(result.get("title") or result.get("code")) for result in results[:3])
    return f"Found {len(results)} semantic SDA library {label} result(s) for '{query}': {titles}."


def _semantic_strict_mode() -> bool:
    return os.getenv("SDA_HYMNBOOK_SEMANTIC_STRICT", "").strip().lower() in {"1", "true", "yes"}


def _embedding_dimensions() -> int:
    value = os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536").strip()
    try:
        return max(1, int(value))
    except ValueError:
        return 1536


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _snippet(text: str, max_chars: int = 420) -> str:
    return _clip(re.sub(r"\s+", " ", text), max_chars)


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


def _request_json(url: str) -> Any:
    with _http_client() as client:
        response = client.get(url, headers={"Accept": "application/json,*/*"})
    if response.status_code >= 400:
        raise SourceHTTPError(url, response.status_code, _clip(response.text, 200))
    return response.json()


def _storage_hymnbook_matches(*, query: str, language: str, limit: int) -> list[dict[str, Any]]:
    catalog = _storage_hymnbook_catalog()
    rows = catalog.get("items", []) if isinstance(catalog, dict) else []
    terms = _terms(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if _clean(item.get("language")).lower() != language:
            continue
        if _clean(item.get("format")).lower() != "pdf":
            continue
        if not _clean(item.get("download_path")):
            continue
        score = _storage_hymnbook_score(item, terms)
        if terms and score <= 0:
            continue
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], _clean(pair[1].get("title")).lower(), _clean(pair[1].get("code"))))
    return [item for _, item in scored[:limit]]


def _storage_hymnbook_score(item: dict[str, Any], terms: list[str]) -> int:
    if not terms:
        return 1
    code = _clean(item.get("code")).lower()
    title = _clean(item.get("title")).lower()
    aliases = " ".join(_clean(alias).lower() for alias in item.get("aliases", []) if alias)
    collection = _clean(item.get("collection")).lower().replace("-", " ")
    provider = _clean(item.get("provider")).lower().replace("-", " ")
    searchable = f"{code} {title} {aliases} {collection} {provider}"
    score = 0
    for term in terms:
        if term == code:
            score += 20
        if term in title:
            score += 10
        if term in aliases:
            score += 8
        if term in searchable:
            score += 2
    return score


def _storage_hymnbook_file(item: dict[str, Any]) -> dict[str, Any]:
    download_path = _clean(item.get("download_path"))
    download_url = _storage_download_url(download_path)
    storage_path = _clean(item.get("storage_path"))
    filename = storage_path.rsplit("/", 1)[-1] if storage_path else download_path.rsplit("/", 1)[-1]
    code = _clean(item.get("code"))
    return {
        "type": "document",
        "label": item.get("title") or code,
        "format": "pdf",
        "mime_type": "application/pdf",
        "filename": filename,
        "url": download_url,
        "download_url": download_url,
        "id": item.get("id"),
        "code": code,
        "title": item.get("title"),
        "language": item.get("language"),
        "collection": item.get("collection"),
        "bytes": item.get("bytes"),
        "sha256": item.get("sha256"),
        "source_url": item.get("source_url"),
        "official_archive_id": item.get("official_archive_id"),
    }


@lru_cache(maxsize=1)
def _storage_hymnbook_catalog() -> dict[str, Any]:
    payload = _request_json(_storage_hymnbook_catalog_url())
    if not isinstance(payload, dict):
        raise ValueError("SDA Library hymnbook catalog returned an invalid payload")
    return payload


def _storage_hymnbook_catalog_url() -> str:
    return f"{_storage_base_url()}{SDA_LIBRARY_HYMNBOOK_CATALOG_PATH}"


def _storage_download_url(download_path: str) -> str:
    path = download_path if download_path.startswith("/") else f"/{download_path}"
    return f"{_storage_base_url()}{path}"


def _storage_base_url() -> str:
    return os.getenv("SDA_LIBRARY_BASE_URL", SDA_LIBRARY_DEFAULT_BASE_URL).rstrip("/")


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


def _hymnbook_search_message(hymnbooks: list[dict[str, Any]], query: str) -> str:
    if not hymnbooks:
        return f"No SDA Library hymnbook metadata matched '{query}'."
    titles = ", ".join(str(hymnbook.get("title") or hymnbook.get("code")) for hymnbook in hymnbooks[:3])
    return f"Found {len(hymnbooks)} SDA Library hymnbook metadata result(s) for '{query}': {titles}."


def _db_url() -> str:
    return os.getenv("SDA_HYMNBOOK_DB_URL", DEFAULT_DB_URL).strip() or DEFAULT_DB_URL


def _language(value: Any) -> str:
    language = _clean(value).lower() or "en"
    if not re.fullmatch(r"[a-z0-9_-]{2,12}", language):
        return "en"
    return language


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


def _terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[a-zA-Z0-9]+", query) if len(term) > 1]
