# Voice Calendar

Voice Calendar is a voice-first calendar backend. The current MVP provides HTTP APIs for Web clients and an MCP-style tool adapter for agents.

## Backend

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Run tests:

```bash
.venv/bin/python -m pytest backend/tests
```

Start the API:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

The API starts at `http://127.0.0.1:8000`.

## Implemented MVP

- Health check: `GET /api/health`
- Event CRUD: `GET/POST/PATCH/DELETE /api/events`
- Undo and confirmation: `POST /api/operations/undo`, `POST /api/operations/confirm`
- Text command entrypoint: `POST /api/text/commands`
- Hot topics and daily briefing: `GET /api/news/today`, `GET /api/calendar/hot-topics`, `GET /api/briefings/daily`
- MCP-style tool adapter: `POST /api/mcp/tools/{tool_name}`

## MCP Tool Examples

```bash
curl -X POST http://127.0.0.1:8000/api/mcp/tools/calendar.list_events \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"start":"2026-05-29T00:00:00+08:00","end":"2026-05-30T00:00:00+08:00"}}'
```

```bash
curl -X POST http://127.0.0.1:8000/api/mcp/tools/news.get_today_hot_topics \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"timezone":"Asia/Shanghai","limit":3,"fresh":true}}'
```

