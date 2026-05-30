# Voice Calendar

Voice Calendar is a voice-first calendar backend. The current MVP provides HTTP APIs for Web clients and an MCP-style tool adapter for agents.

## Backend

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Enable local voice recognition:

```bash
.venv/bin/python -m pip install -e '.[voice]'
```

This installs `faster-whisper`. The first real ASR request may still download model weights.
If Hugging Face access is blocked, the backend defaults to `https://hf-mirror.com`.

Run tests:

```bash
.venv/bin/python -m pytest backend/tests
```

Start the API:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

The API starts at `http://127.0.0.1:8000`.

Open the Web workspace:

```text
http://127.0.0.1:8000/
```

Run the standalone MCP server over stdio:

```bash
.venv/bin/python -m app.mcp_entry
```

Run the standalone MCP HTTP server:

```text
.venv/bin/python -m app.mcp_http_entry
```

Default MCP HTTP endpoint:

```text
http://127.0.0.1:8001/mcp
```

Optional ASR configuration:

Local `faster-whisper` is now the default ASR provider. The default model set is:

- `VOICE_ASR_PROVIDER=faster-whisper`
- `VOICE_ASR_MODEL=base`
- `VOICE_ASR_DEVICE=cpu`
- `VOICE_ASR_COMPUTE_TYPE=int8`
- `VOICE_ASR_PRELOAD_ON_STARTUP=false`

If you want to force those values explicitly:

```bash
export VOICE_ASR_PROVIDER="faster-whisper"
export VOICE_ASR_MODEL="base"
export VOICE_ASR_DEVICE="cpu"
export VOICE_ASR_COMPUTE_TYPE="int8"
export VOICE_ASR_PRELOAD_ON_STARTUP="false"
```

Optional third-party ASR / agent services:

```bash
export VOICE_ASR_API_URL="https://your-asr-provider.example/v1/audio/transcriptions"
export VOICE_ASR_API_KEY="your-asr-key"
export VOICE_ASR_MODEL="your-asr-model"

export VOICE_AGENT_API_URL="https://your-agent-provider.example/v1/chat/completions"
export VOICE_AGENT_API_KEY="your-agent-key"
export VOICE_AGENT_MODEL="your-agent-model"
```

## Implemented MVP

- Health check: `GET /api/health`
- Event CRUD: `GET/POST/PATCH/DELETE /api/events`
- Undo and confirmation: `POST /api/operations/undo`, `POST /api/operations/confirm`
- Text command entrypoint: `POST /api/text/commands`
- Voice command entrypoint: `POST /api/voice/commands`
- Voice capability probe: `GET /api/voice/capabilities`
- Hot topics and daily briefing: `GET /api/news/today`, `GET /api/calendar/hot-topics`, `GET /api/briefings/daily`
- MCP-style tool adapter: `POST /api/mcp/tools/{tool_name}`
- Standard MCP server: stdio via `python -m app.mcp_entry`, streamable HTTP via standalone `python -m app.mcp_http_entry`
- Desktop Web workspace: `GET /`

## Desktop Overlay

A desktop floating overlay now lives in `desktop-overlay/`.

Install and run:

```bash
cd desktop-overlay
npm install
npm start
```

Default behavior:

- Always-on-top frameless desktop window
- Text command entry that calls `calendar.handle_command`
- Voice recording that base64-encodes audio and calls `voice.handle_command`
- Text and voice now both execute through MCP tools
- "打开日历" opens the full Web workspace in the browser

Optional backend override:

```bash
export VOICE_CALENDAR_API_BASE="http://127.0.0.1:8000"
export VOICE_CALENDAR_MCP_BASE="http://127.0.0.1:8001"
```

## Web Workspace

The desktop workspace follows a three-column layout:

- Left: real-time hot topics
- Center: FullCalendar-powered year/month/week/day/list calendar
- Right: selected-day agenda
- Floating voice control: backend audio upload first, browser speech recognition fallback

The page calls the backend APIs directly, so start the API and open `http://127.0.0.1:8000/`.

## Command Pipeline

The backend now uses a three-layer voice pipeline:

1. `ASR`: `/api/voice/commands` accepts audio and uses local `faster-whisper` by default, while still supporting configurable third-party ASR APIs.
2. `NLU`: rule-based parsing produces `intent`, `slots`, `missing_fields`, and confidence.
3. `Agent fallback`: when rules are uncertain or unsupported, a configurable third-party agent can return structured JSON for the same command.

Web text commands, Web voice commands, and `calendar.parse_command` all reuse the same parsing flow.

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

Web-facing backend capabilities are also exposed through MCP tools, including:

- `calendar.get_event`
- `calendar.create_event`
- `calendar.update_event`
- `calendar.delete_event`
- `calendar.get_meta`
- `calendar.get_hot_topic_panel`
- `news.refresh_hot_topics`
- `voice.get_capabilities`
- `voice.transcribe_audio`
- `voice.handle_command`
