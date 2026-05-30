from __future__ import annotations

from app.services.mcp_server import build_mcp_server


def main() -> None:
    server = build_mcp_server()
    server.run(transport="stdio")


def run_http() -> None:
    server = build_mcp_server(streamable_http_path="/mcp")
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
