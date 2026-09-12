"""Exercise the command written to Codex, including package tool registration."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import PaginatedRequestParams
import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.skipif(sys.version_info < (3, 11), reason="The installer manager requires Python 3.11+ and provisions Python 3.12; server-only Python 3.10 is tested separately.")
async def test_installed_command_discovers_tools_and_serves_guidance_without_rhino(tmp_path):
    spec = importlib.util.spec_from_file_location("entrypoint_installer", ROOT / "distribution/manager.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    settings = installer.server_settings(Path(sys.executable))
    # Reserve an unused port without listening, so no real Rhino can be reached.
    with socket.socket() as reserved_port:
        reserved_port.bind(("127.0.0.1", 0))
        environment = dict(os.environ, **settings["env"])
        environment.update(PYTHONPATH=str(ROOT / "server/src"),
                           RHINO_MCP_PORT=str(reserved_port.getsockname()[1]), RHINO_MCP_TIMEOUT="0.1")
        parameters = StdioServerParameters(command=settings["command"], args=settings["args"],
                                           env=environment, cwd=tmp_path)
        with (tmp_path / "server-stderr.log").open("w", encoding="utf-8") as stderr:
            async with stdio_client(parameters, errlog=stderr) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=20) as session:
                    initialized = await session.initialize()
                    assert initialized.server_info.name == "RhinoMCP"
                    names = set()
                    cursor = None
                    while True:
                        page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
                        names.update(tool.name for tool in page.tools)
                        cursor = page.next_cursor
                        if cursor is None:
                            break
                    assert {"create_wall", "create_floor_slab", "get_document_summary", "get_management_status",
                            "gh_build_graph", "gh_get_graph", "get_modeling_guidance"} <= names
                    result = await session.call_tool("get_modeling_guidance", {"topic": "architecture"})
                    assert not result.is_error
                    content = result.structured_content
                    if content is None:
                        content = json.loads("\n".join(item.text for item in result.content if hasattr(item, "text")))
                    if isinstance(content, dict) and set(content) == {"result"}:
                        content = content["result"]
                    assert content["topic"] == "architecture"
                    assert content["guidance_version"] == "4"
                    assert content["content"].startswith("# ")
                    assert "Grasshopper" in content["content"]
    assert "found in sys.modules" not in (tmp_path / "server-stderr.log").read_text(encoding="utf-8")
