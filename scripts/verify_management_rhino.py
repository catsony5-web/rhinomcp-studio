"""Verify maintenance in an installed Rhino bridge and real MCP stdio session.

Requires a dedicated empty Rhino document and the local owner validation service.
Creates one named test box and deletes only its returned ID in finally.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from verify_management import Admin


def unwrap(result):
    if result.is_error:
        raise RuntimeError("\n".join(getattr(c, "text", "") for c in result.content))
    value = result.structured_content
    if value is None:
        value = "\n".join(getattr(c, "text", "") for c in result.content)
    for _ in range(4):
        if isinstance(value, dict) and set(value) == {"result"}:
            value = value["result"]
        elif isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                break
        else:
            break
    if isinstance(value, dict) and value.get("success") is False:
        raise RuntimeError(str(value))
    return value


async def run(args):
    admin = Admin("http://127.0.0.1:8765", (args.private_dir / "administrator-password.txt").read_text(encoding="utf8").strip())
    report = {"scope": "Installed Windows Rhino 8 + MCP stdio + real local management HTTP", "checks": []}
    def passed(name):
        report["checks"].append({"name": name, "passed": True})
        print("PASS", name, flush=True)
    env = dict(os.environ, PYTHONUTF8="1", RHINO_MCP_REQUIRE_MATCH="1", RHINO_MCP_VALIDATE="strict", RHINO_MCP_TIMEOUT="30")
    env.pop("PYTHONPATH", None)
    params = StdioServerParameters(command=str(args.server_python.resolve()), args=["-m", "rhinomcp"], env=env, cwd=tempfile.gettempdir())
    created = None
    started = args.private_dir / ("inflight-" + uuid.uuid4().hex + ".txt")
    finished = started.with_suffix(".finished.txt")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=40) as session:
            await session.initialize()
            async def call(name, arguments=None):
                return unwrap(await session.call_tool(name, arguments or {}, read_timeout_seconds=40))
            async def policy(**kwargs):
                await asyncio.to_thread(admin.policy, "/admin/policy", **kwargs)
            async def refused(name, arguments, marker):
                result = await session.call_tool(name, arguments, read_timeout_seconds=40)
                text = "\n".join(getattr(c, "text", "") for c in result.content)
                assert result.is_error and marker in text, text
            try:
                await policy(paused="0", reason="", minimum_version="")
                report["capabilities"] = await call("describe_capabilities")
                assert report["capabilities"]["version"].startswith("0.6.1")
                assert report["capabilities"]["plugin_matches_server"] is True
                before = await call("get_document_summary")
                assert before["object_count"] == 0, "Native geometry verification requires an empty document"
                passed("installed_version_and_empty_document")
                box = {"type": "BOX", "name": "MCP management verification " + uuid.uuid4().hex, "params": {"width": 100, "length": 100, "height": 100}}
                created = (await call("create_object", box))["id"]
                assert (await call("get_document_summary"))["object_count"] == 1
                passed("online_approved_real_geometry_creation")
                await policy(paused="1", reason="Native MCP maintenance check", minimum_version="")
                await refused("create_object", box, "Native MCP maintenance check")
                status = await call("get_management_status")
                assert status["configured"] and status["state"] == "blocked", status
                passed("maintenance_refuses_real_mcp_creation_status_remains_available")
                await policy(paused="0", reason="", minimum_version="")
                assert (await call("get_document_summary"))["object_count"] == 1
                passed("resume_and_no_geometry_created_while_paused")
                await asyncio.to_thread(admin.policy, "/admin/version", version="0.6.1", paused="1", reason="Native version maintenance")
                await refused("create_object", box, "Native version maintenance")
                await asyncio.to_thread(admin.policy, "/admin/version", version="0.6.1", paused="0", reason="")
                passed("native_version_pause_and_resume")
                # Both sentinels prove policy saving overlaps actual Rhino execution.
                code = ('System.IO.File.WriteAllText(' + json.dumps(str(started.resolve()), ensure_ascii=False)
                        + ',"started"); System.Threading.Thread.Sleep(5000); System.IO.File.WriteAllText('
                        + json.dumps(str(finished.resolve()), ensure_ascii=False)
                        + ',"finished"); output.AppendLine("completed");')
                running = asyncio.create_task(call("execute_rhinocommon_csharp_code", {"code": code}))
                for _ in range(150):
                    if started.exists() or running.done():
                        break
                    await asyncio.sleep(.05)
                if not started.exists():
                    await running
                    raise AssertionError("In-flight verification never started")
                await policy(paused="1", reason="In-flight preservation check", minimum_version="")
                assert not finished.exists() and not running.done(), "Maintenance was not saved before the in-flight script finished"
                report["policy_saved_while_script_running"] = True
                completed = await running
                assert completed["success"] is True and "completed" in completed["output"]
                await refused("create_object", box, "In-flight preservation check")
                passed("already_running_script_finishes_next_request_is_refused")
                await policy(paused="0", reason="", minimum_version="")
                assert (await call("get_document_summary"))["object_count"] == 1
            finally:
                await policy(paused="0", reason="", minimum_version="")
                await asyncio.to_thread(admin.policy, "/admin/version", version="0.6.1", paused="0", reason="")
                if created:
                    await call("delete_object", {"id": created})
                    assert (await call("get_document_summary"))["object_count"] == 0
                    passed("test_object_cleaned_original_empty_document_preserved")
                report["final_status"] = await call("get_management_status")
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"PASS {len(report['checks'])} native Rhino checks")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--server-python", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
