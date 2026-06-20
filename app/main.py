from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from agentnet_mcp_sdk import AgentApp
from agentnet_mcp_sdk.models import AuthConfig

from app.manifest import SERVER_DISPLAY_NAME, SERVER_NAME, SERVER_VERSION, SLUG, TOOLS
from app.tools import call_tool


agent_app = AgentApp(
    name=SERVER_DISPLAY_NAME,
    server_name=SERVER_NAME,
    slug=SLUG,
    tagline="Live SDA Hymnal search, numbers, titles, and lyrics for edge agents.",
    description=(
        "SDA Hymnbook MCP Server reads a live SDA Hymnal source database for hymn "
        "number search, title search, lyrics, source links, and version metadata."
    ),
    category="music",
    version=SERVER_VERSION,
    icon_path="sda-hymnbook-icon.svg",
    static_dir="app/static",
    auth=AuthConfig(is_auth_required=False, auth_type="none"),
)


def create_app() -> FastAPI:
    return agent_app.create_fastapi_app()


def _call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return call_tool(
        tool_name,
        {key: value for key, value in arguments.items() if value is not None},
    )


def _tool_kwargs(tool_name: str) -> dict[str, Any]:
    tool = _tool_metadata(tool_name)
    return {
        "name": tool["name"],
        "title": tool["title"],
        "description": tool["description"],
        "input_schema": tool["input_schema"],
        "output_schema": tool["output_schema"],
        "is_destructive": tool["is_destructive"],
        "requires_user_confirmation": tool["requires_user_confirmation"],
    }


def _tool_metadata(tool_name: str) -> dict[str, Any]:
    for tool in TOOLS:
        if tool["name"] == tool_name:
            return tool
    raise KeyError(tool_name)


@agent_app.tool(**_tool_kwargs("search_hymns"))
def search_hymns(
    query: str | None = None,
    number: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Search the live SDA Hymnal source."""
    return _call("search_hymns", locals())


@agent_app.tool(**_tool_kwargs("get_hymn"))
def get_hymn(
    number: int | None = None,
    title: str | None = None,
    include_lyrics: bool | None = None,
) -> dict[str, Any]:
    """Resolve a hymn from the live SDA Hymnal source."""
    return _call("get_hymn", locals())


@agent_app.tool(**_tool_kwargs("get_hymn_lyrics"))
def get_hymn_lyrics(number: int | None = None) -> dict[str, Any]:
    """Return hymn lyrics from the live SDA Hymnal source."""
    return _call("get_hymn_lyrics", locals())


@agent_app.tool(**_tool_kwargs("list_hymnbook_versions"))
def list_hymnbook_versions() -> dict[str, Any]:
    """List live source/version metadata."""
    return _call("list_hymnbook_versions", locals())


@agent_app.tool(**_tool_kwargs("download_hymn"))
def download_hymn(
    number: int | None = None,
    format: str | None = None,
) -> dict[str, Any]:
    """Return live hymn source links."""
    return _call("download_hymn", locals())


app = create_app()
