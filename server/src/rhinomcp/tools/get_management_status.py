"""Local diagnostics for the managed Rhino bridge; contains no credentials."""

from typing import Any, Dict

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from rhinomcp.server import get_rhino_connection, mcp


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def get_management_status(ctx: Context) -> Dict[str, Any]:
    """Read registration and the last authorization result, even during maintenance.

    This is local status, not a fresh permission to model. Every actual Rhino
    command requires its own online approval. A paused, unreachable or invalid
    management service blocks new commands. Show the reason and recovery advice;
    do not switch to scripts, another transport or an older version to bypass it.
    Already running work and manual Rhino editing/saving are unaffected.
    """
    return get_rhino_connection().send_command("get_management_status", {})
