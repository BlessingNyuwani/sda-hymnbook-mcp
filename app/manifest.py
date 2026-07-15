from __future__ import annotations

from typing import Any



SERVER_NAME = "sda-hymnbook-mcp-server"
SERVER_DISPLAY_NAME = "SDA Hymnbook"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-03-26"
SLUG = "sda-hymnbook"

PERMISSIONS: list[dict[str, Any]] = []
EXECUTION_MODES = ["online"]


def execution_targets(server_url: str) -> list[dict[str, Any]]:
    return [
        {
            "mode": "online",
            "type": "remote_mcp",
            "url": server_url,
            "transport": "streamable_http",
            "endpoint": "/mcp",
        },
    ]

STANDARD_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "success": {"type": "boolean"},
        "message": {"type": "string"},
        "content": {"type": "string"},
        "content_type": {"type": "string"},
        "presentation_hint": {"type": "string"},
        "context": {"type": "string"},
        "files": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "artifacts": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "sources": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
    },
    "required": ["status", "success", "message", "content", "content_type", "presentation_hint", "context"],
    "additionalProperties": True,
}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_hymns",
        "title": "Search SDA hymns",
        "description": (
            "Search a live SDA Hymnal SQLite source by hymn number, title, lyrics, "
            "refrain, section, or keyword."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Title, lyric, or keyword."},
                "number": {"type": "integer", "minimum": 1, "maximum": 2000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            "required": [],
            "anyOf": [
                {"required": ["query"]},
                {"required": ["number"]},
            ],
            "additionalProperties": False,
        },
        "output_schema": STANDARD_OUTPUT_SCHEMA,
        "is_destructive": False,
        "requires_user_confirmation": False,
    },
    {
        "name": "search_hymnbooks",
        "title": "Search SDA hymnbook PDFs",
        "description": (
            "Search inside stored SDA Library hymnbook PDFs semantically using the "
            "shared pgvector index, with metadata fallback."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Phrase or topic to search inside hymnbook PDFs."},
                "language": {"type": "string", "default": "en"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": STANDARD_OUTPUT_SCHEMA,
        "is_destructive": False,
        "requires_user_confirmation": False,
    },
    {
        "name": "get_hymn",
        "title": "Get hymn",
        "description": "Resolve a hymn by number or title from the live SDA Hymnal source.",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer", "minimum": 1, "maximum": 2000},
                "title": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Natural request such as hymn number 100.",
                },
                "include_lyrics": {"type": "boolean", "default": True},
            },
            "required": [],
            "anyOf": [
                {"required": ["number"]},
                {"required": ["title"]},
                {"required": ["query"]},
            ],
            "additionalProperties": False,
        },
        "output_schema": STANDARD_OUTPUT_SCHEMA,
        "is_destructive": False,
        "requires_user_confirmation": False,
    },
    {
        "name": "get_hymn_lyrics",
        "title": "Get hymn lyrics",
        "description": "Return hymn lyrics from the live SDA Hymnal source by hymn number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer", "minimum": 1, "maximum": 2000},
                "title": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Natural request such as lyrics for hymn 100.",
                },
            },
            "required": [],
            "anyOf": [
                {"required": ["number"]},
                {"required": ["title"]},
                {"required": ["query"]},
            ],
            "additionalProperties": False,
        },
        "output_schema": STANDARD_OUTPUT_SCHEMA,
        "is_destructive": False,
        "requires_user_confirmation": False,
    },
    {
        "name": "list_hymnbook_versions",
        "title": "List hymnbook versions",
        "description": (
            "List available live hymnbook source/version metadata and future version "
            "capabilities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "output_schema": STANDARD_OUTPUT_SCHEMA,
        "is_destructive": False,
        "requires_user_confirmation": False,
    },
    {
        "name": "download_hymn",
        "title": "Get hymnbook download",
        "description": (
            "Return stored SDA Library hymnbook PDF download links using shorter "
            "natural wording."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "integer", "minimum": 1, "maximum": 2000},
                "query": {"type": "string", "description": "Hymnbook title or code, such as Hymns and Tunes or HT1888."},
                "code": {"type": "string", "description": "Hymnbook code such as HT1888 or SM1885."},
                "title": {"type": "string"},
                "language": {"type": "string", "default": "en"},
                "format": {
                    "type": "string",
                    "enum": ["pdf", "all"],
                    "default": "pdf",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        "output_schema": STANDARD_OUTPUT_SCHEMA,
        "is_destructive": False,
        "requires_user_confirmation": False,
    },
    {
        "name": "download_hymnbook",
        "title": "Download hymnbook",
        "description": "Find stored SDA Library hymnbook PDFs and return local download links.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Hymnbook title or code, such as Hymns and Tunes or HT1888."},
                "code": {"type": "string", "description": "Hymnbook code such as HT1888 or SM1885."},
                "title": {"type": "string"},
                "language": {"type": "string", "default": "en"},
                "format": {
                    "type": "string",
                    "enum": ["pdf", "all"],
                    "default": "pdf",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        "output_schema": STANDARD_OUTPUT_SCHEMA,
        "is_destructive": False,
        "requires_user_confirmation": False,
    },
]


def mcp_tool_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "title": tool["title"],
            "description": tool["description"],
            "inputSchema": tool["input_schema"],
            "annotations": {
                "readOnlyHint": not tool["is_destructive"],
                "destructiveHint": tool["is_destructive"],
                "openWorldHint": True,
            },
        }
        for tool in TOOLS
    ]


def public_manifest(
    server_url: str,
    health_check_url: str,
    icon_url: str | None = None,
) -> dict[str, Any]:
    return {
        "name": SERVER_NAME,
        "display_name": SERVER_DISPLAY_NAME,
        "version": SERVER_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "transport": "streamable_http",
        "server_url": server_url,
        "health_check_url": health_check_url,
        "icon_url": icon_url,
        "execution_modes": EXECUTION_MODES,
        "execution_targets": execution_targets(server_url),
        "tools": TOOLS,
        "permissions": PERMISSIONS,
    }


def hub_registration_payload(
    server_url: str,
    health_check_url: str,
    icon_url: str | None = None,
) -> dict[str, Any]:
    return {
        "name": SERVER_DISPLAY_NAME,
        "slug": SLUG,
        "tagline": "Live SDA Hymnal search, numbers, titles, and lyrics.",
        "description": (
            "Search SDA hymns by number, title, lyric, or keyword, read hymn "
            "lyrics directly, and download available SDA Library hymnbook PDFs."
        ),
        "category": "music",
        "version": SERVER_VERSION,
        "icon_url": icon_url,
        "execution_modes": EXECUTION_MODES,
        "execution_targets": execution_targets(server_url),
        "mcp_server": {
            "name": SERVER_DISPLAY_NAME,
            "server_url": server_url,
            "transport": "streamable_http",
            "protocol_version": PROTOCOL_VERSION,
            "health_check_url": health_check_url,
            "connection_config": {
                "docs_url": server_url.replace("/mcp", "/docs"),
                "manifest_url": server_url.replace("/mcp", "/manifest"),
                "execution_modes": EXECUTION_MODES,
                "execution_targets": execution_targets(server_url),
            },
        },
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
                "output_schema": tool["output_schema"],
                "is_destructive": tool["is_destructive"],
                "requires_user_confirmation": tool["requires_user_confirmation"],
            }
            for tool in TOOLS
        ],
        "permissions": [],
        "is_auth_required": False,
        "auth_type": "none",
        "auth_instructions": None,
        "connection_schema": None,
    }
