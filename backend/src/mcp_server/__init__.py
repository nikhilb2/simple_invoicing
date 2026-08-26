"""Model Context Protocol server embedded in the FastAPI app.

Deliberately named ``mcp_server`` rather than ``mcp`` so it never shadows (or is
mistaken for) the ``mcp`` PyPI package — which this package intentionally does
not depend on: the transport is hand-rolled in :mod:`src.mcp_server.transport`.

The only entry point the application needs is :func:`register_mcp`.
"""

from src.mcp_server.transport import register_mcp

__all__ = ["register_mcp"]
