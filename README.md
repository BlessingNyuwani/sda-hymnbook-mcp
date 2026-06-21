# SDA Hymnbook MCP Server

Live MCP server for SDA hymns.

## Runtime data

This server does not ship seeded hymn records. Hymn search and lyric tool calls fetch the live SDA Hymnal SQLite source from:

`https://raw.githubusercontent.com/joshpetit/sda-hymnal/master/data/hymns.db`

The database is queried at runtime for hymn numbers, titles, sections, refrains, and verses.

Hymnbook downloads are resolved from the SDA Library storage catalog:

- `https://sda-library.marona.ai/catalog/hymnbooks.json`
- local PDF download URLs under `https://sda-library.marona.ai/downloads/...`
- stored official archive PDFs such as `HT1888.pdf` and `SM1885.pdf`

## Tools

- `search_hymns`
- `get_hymn`
- `get_hymn_lyrics`
- `list_hymnbook_versions`
- `download_hymn`
- `download_hymnbook`

## Local run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 62752
```

Production domain: `https://sda-hymnbook.marona.ai`
