from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.manifest import hub_registration_payload


APP_UPDATE_FIELDS = {
    "name",
    "slug",
    "tagline",
    "description",
    "category",
    "version",
    "icon_url",
    "execution_modes",
    "execution_targets",
    "mcp_server",
    "is_auth_required",
    "auth_type",
    "auth_instructions",
    "connection_schema",
    "terms_url",
    "privacy_url",
}


def agent_app_payload(registration: dict) -> dict:
    payload = {key: value for key, value in registration.items() if key in APP_UPDATE_FIELDS and value is not None}
    payload["tools"] = []
    payload["permissions"] = []
    return payload


def request_json(method: str, url: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict | list | None]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Register SDA Hymnbook with Marona Hub.")
    parser.add_argument("--hub-url", default=os.getenv("MCP_HUB_URL", "https://hub.marona.ai"))
    parser.add_argument("--email", default=os.getenv("MCP_HUB_DEVELOPER_EMAIL", "developer@mcphub.dev"))
    parser.add_argument("--password", default=os.getenv("MCP_HUB_DEVELOPER_PASSWORD", "ChangeMe123!"))
    parser.add_argument("--server-url", default=os.getenv("SDA_HYMNBOOK_MCP_SERVER_URL", "https://sda-hymnbook.marona.ai/mcp/"))
    parser.add_argument("--health-url", default=os.getenv("SDA_HYMNBOOK_MCP_HEALTH_URL", "https://sda-hymnbook.marona.ai/health"))
    parser.add_argument("--icon-url", default=os.getenv("SDA_HYMNBOOK_MCP_ICON_URL", "https://sda-hymnbook.marona.ai/static/sda-hymnbook-icon.svg"))
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    hub_url = args.hub_url.rstrip("/")
    login_status, login_payload = request_json("POST", f"{hub_url}/auth/login", {"email": args.email, "password": args.password})
    if login_status >= 400 or not isinstance(login_payload, dict):
        print(json.dumps({"error": "login failed", "status": login_status, "payload": login_payload}, indent=2))
        return 1

    token = login_payload["access_token"]
    registration = hub_registration_payload(args.server_url, args.health_url, args.icon_url)
    create_status, create_payload = request_json("POST", f"{hub_url}/portal/developer/agent-apps", agent_app_payload(registration), token)

    if create_status == 409:
        _, apps = request_json("GET", f"{hub_url}/portal/developer/agent-apps", token=token)
        existing = next((app for app in apps if app.get("slug") == registration["slug"]), None) if isinstance(apps, list) else None
        if not existing:
            print(json.dumps({"registered": False, "reason": "slug already exists"}, indent=2))
            return 1
        update_payload = agent_app_payload(registration)
        update_payload.pop("tools", None)
        update_payload.pop("permissions", None)
        update_status, update_response = request_json("PUT", f"{hub_url}/portal/developer/agent-apps/{existing['id']}", update_payload, token)
        if update_status >= 400:
            print(json.dumps({"error": "update existing failed", "status": update_status, "payload": update_response}, indent=2))
            return 1
        app_id = existing["id"]
        registered = False
        updated_existing = True
    elif create_status >= 400 or not isinstance(create_payload, dict):
        print(json.dumps({"error": "registration failed", "status": create_status, "payload": create_payload}, indent=2))
        return 1
    else:
        app_id = create_payload["id"]
        registered = True
        updated_existing = False

    sync_status, sync_payload = request_json("POST", f"{hub_url}/portal/developer/agent-apps/{app_id}/sync-mcp-server", token=token)
    if sync_status >= 400 or not isinstance(sync_payload, dict):
        print(json.dumps({"error": "mcp sync failed", "status": sync_status, "payload": sync_payload}, indent=2))
        return 1

    result = {
        "registered": registered,
        "updated_existing": updated_existing,
        "agent_app_id": sync_payload["id"],
        "slug": sync_payload["slug"],
        "status": sync_payload["status"],
        "server_url": args.server_url,
        "tools_count": len(sync_payload.get("tools") or []),
        "permissions_count": len(sync_payload.get("permissions") or []),
    }
    if args.submit:
        submit_status, submit_payload = request_json(
            "POST",
            f"{hub_url}/portal/developer/agent-apps/{sync_payload['id']}/submit",
            {"comments": "Submitted from sda-hymnbook-mcp registration script after MCP sync."},
            token,
        )
        result["submit_status_code"] = submit_status
        result["submitted"] = submit_status < 400
        if isinstance(submit_payload, dict):
            result["status"] = submit_payload.get("status", result["status"])

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
