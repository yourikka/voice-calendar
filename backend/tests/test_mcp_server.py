from mcp.server.fastmcp import FastMCP

from app.services.mcp_server import build_mcp_server


def test_build_mcp_server_exposes_named_tools() -> None:
    server = build_mcp_server()

    assert isinstance(server, FastMCP)
    tools = server._tool_manager.list_tools()
    tool_names = {tool.name for tool in tools}
    assert "calendar.parse_command" in tool_names
    assert "calendar.get_event" in tool_names
    assert "calendar.create_event" in tool_names
    assert "calendar.create_event_draft" in tool_names
    assert "calendar.resolve_candidate" in tool_names
    assert "calendar.delete_event" in tool_names
    assert "calendar.get_meta" in tool_names
    assert "calendar.get_hot_topic_panel" in tool_names
    assert "news.get_today_hot_topics" in tool_names
    assert "news.refresh_hot_topics" in tool_names
    assert "briefing.get_daily_briefing" in tool_names
    assert "voice.get_capabilities" in tool_names
    assert "voice.transcribe_audio" in tool_names
    assert "voice.handle_command" in tool_names


def test_build_mcp_server_configures_streamable_http_defaults() -> None:
    server = build_mcp_server("/mcp")

    assert server.settings.host == "127.0.0.1"
    assert server.settings.port == 8001
    assert server.settings.streamable_http_path == "/mcp"
