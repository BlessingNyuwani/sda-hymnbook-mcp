# SDA Hymnbook MCP Server

Live MCP server for SDA hymns.

## Runtime data

This server does not ship seeded hymn records. Tool calls fetch the live SDA Hymnal SQLite source from:

`https://raw.githubusercontent.com/joshpetit/sda-hymnal/master/data/hymns.db`

The database is queried at runtime for hymn numbers, titles, sections, refrains, and verses.

## Tools

- `search_hymns`
- `get_hymn`
- `get_hymn_lyrics`
- `list_hymnbook_versions`
- `download_hymn`

## Local run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 62752
```

Production domain: `https://sda-hymnbook.marona.ai`
