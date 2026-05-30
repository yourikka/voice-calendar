from mcp.server.fastmcp import FastMCP

from app.main import mcp_app
from app.services.mcp_server import build_mcp_server


def test_build_mcp_server_exposes_named_tools() -> None:
    server = build_mcp_server()

    assert isinstance(server, FastMCP)
    tools = server._tool_manager.list_tools()
    tool_names = {tool.name for tool in tools}
    assert "calendar.parse_command" in tool_names
    assert "calendar.create_event_draft" in tool_names
    assert "news.get_today_hot_topics" in tool_names
    assert "briefing.get_daily_briefing" in tool_names


def test_main_mounts_streamable_http_mcp_app() -> None:
    assert mcp_app is not None
