from __future__ import annotations

from app.services.mcp_server import build_mcp_server


def main() -> None:
    server = build_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
