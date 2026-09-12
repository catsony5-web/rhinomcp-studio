"""Verify the Studio MCP surface and, explicitly, an empty live Rhino document.

Run with server/.venv/Scripts/python.exe scripts/verify_studio.py.
Add --live only with a separate empty Rhino document. No full mcptest, document
reset, or broad object deletion is performed. Reports include skipped checks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import PaginatedRequestParams


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOOLS = {
    "create_wall", "create_floor_slab", "describe_capabilities", "analyze_objects",
    "get_document_summary", "get_modeling_guidance", "boolean_union",
    "boolean_difference", "boolean_intersection", "extrude_curve", "modify_objects",
    "undo", "redo", "execute_rhinocommon_csharp_code", "gh_build_graph",
    "gh_get_graph", "gh_clear_graph", "gh_get_parameter_value",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class SkipCheck(Exception):
    """A check was deliberately not executed to preserve existing work."""


def decode_result(result: Any) -> Any:
    if getattr(result, "is_error", False):
        raise RuntimeError("; ".join(getattr(item, "text", "") for item in result.content))
    value = getattr(result, "structured_content", None)
    if value is None:
        value = "\n".join(getattr(item, "text", "") for item in result.content)
    for _ in range(3):
        if isinstance(value, dict) and set(value) == {"result"}:
            value = value["result"]
        elif isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                break
        else:
            break
    if isinstance(value, dict) and (value.get("success") is False or value.get("status") == "error"):
        raise RuntimeError(str(value.get("message", value)))
    if isinstance(value, str) and value.lower().startswith(("error", "failed")):
        raise RuntimeError(value)
    return value


class Verification:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.session: ClientSession | None = None
        self.document_serial: int | None = None
        self.owned_ids: set[str] = set()
        self.graph_id: str | None = None
        self.graph_component_ids: set[str] = set()
        self.report: dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "mode": "live" if args.live else "nonlive",
            "server_python": args.server_python,
            "server_launch_mode": "installed" if args.installed else "source",
            "source_root": None if args.installed else str(ROOT),
            "source_path_injected": not args.installed,
            "checks": [],
        }

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return decode_result(await self.session.call_tool(
            name, arguments or {}, read_timeout_seconds=self.args.timeout
        ))

    async def check(self, name: str, operation: Any) -> Any:
        started = time.monotonic()
        item: dict[str, Any] = {"name": name}
        self.report["checks"].append(item)
        try:
            value = await operation()
            item.update(status="passed", details=value)
            print(f"PASS {name}", flush=True)
            return value
        except SkipCheck as reason:
            item.update(status="skipped", reason=str(reason))
            print(f"SKIP {name}: {reason}", flush=True)
            return None
        except Exception as error:
            item.update(status="failed", error=str(error))
            print(f"FAIL {name}: {error}", flush=True)
            raise
        finally:
            item["duration_seconds"] = round(time.monotonic() - started, 3)

    async def script(self, code: str) -> str:
        result = await self.call("execute_rhinocommon_csharp_code", {"code": code})
        require(isinstance(result, dict) and result.get("success") is True, "C# test script did not succeed")
        return result.get("output", "").strip()

    async def guard_document(self, *, empty: bool = False) -> int:
        code = "if (doc == null) throw new Exception(\"No active test document\");\n"
        if self.document_serial is not None:
            code += f'if (doc.RuntimeSerialNumber != {self.document_serial}u) throw new Exception("Active Rhino document changed; test stopped");\n'
        if empty:
            code += (
                'var settings = new Rhino.DocObjects.ObjectEnumeratorSettings {\n'
                'NormalObjects = true, LockedObjects = true, HiddenObjects = true,\n'
                'ActiveObjects = true, ReferenceObjects = true, IdefObjects = true,\n'
                'IncludeLights = true, IncludeGrips = true, DeletedObjects = false };\n'
                'if (doc.Objects.GetObjectList(settings).Any()) throw new Exception("Live verification requires a separate empty Rhino document, including hidden and locked objects");\n'
            )
        code += "output.AppendLine(doc.RuntimeSerialNumber.ToString());"
        serial = int(await self.script(code))
        if self.document_serial is None:
            self.document_serial = serial
        return serial

    async def inspect_surface(self) -> dict[str, Any]:
        initialization = await self.session.initialize()
        tools = []
        cursor = None
        while True:
            page = await self.session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                break
        names = [tool.name for tool in tools]
        require(len(names) == len(set(names)), "Duplicate MCP tool names")
        require(REQUIRED_TOOLS <= set(names), f"Missing tools: {sorted(REQUIRED_TOOLS - set(names))}")
        for tool in tools:
            Draft202012Validator.check_schema(tool.input_schema)
            if tool.output_schema is not None:
                Draft202012Validator.check_schema(tool.output_schema)
            require(bool(tool.description), f"Tool {tool.name} is missing its description")
        guidance = await self.call("get_modeling_guidance", {"topic": "recovery"})
        require(isinstance(guidance, dict) and bool(guidance.get("content")), "Packaged modeling guidance is unavailable")
        return {
            "protocol_version": initialization.protocol_version,
            "server_info": initialization.server_info.model_dump(mode="json"),
            "tool_count": len(tools), "tools": sorted(names),
            "input_schemas_valid": True, "guidance_version": guidance.get("guidance_version"),
        }

    async def modeling_safety(self) -> dict[str, Any]:
        await self.guard_document(empty=True)
        output = await self.script(
            'var assembly = AppDomain.CurrentDomain.GetAssemblies().Single(a => a.GetName().Name == "rhinomcp");\n'
            'var type = assembly.GetType("RhinoMCPPlugin.Functions.RhinoMCPFunctions", true);\n'
            'var method = type.GetMethod("TestModelingSafety");\n'
            'if (method == null) throw new Exception("Installed plugin lacks TestModelingSafety");\n'
            'output.AppendLine(method.Invoke(Activator.CreateInstance(type), null).ToString());'
        )
        results = json.loads(output)
        require(bool(results), "Modeling regression test returned no results")
        failures = {name: value for name, value in results.items() if value.get("status") != "pass"}
        self.report["modeling_regressions"] = results
        require(not failures, f"Modeling regression failures: {failures}")
        await self.guard_document(empty=True)
        return results

    async def capabilities(self) -> dict[str, Any]:
        result = await self.call("describe_capabilities")
        require(result.get("plugin_matches_server") is True, f"Server/plugin version agreement is not verified: {result.get('update_advice') or result}")
        return result

    async def architectural_solid(self, tool: str, parameters: dict[str, Any],
                                  volume: float, bounds: list[list[float]]) -> dict[str, Any]:
        await self.guard_document()
        parameters = dict(parameters, name="StudioVerification_" + uuid4().hex)
        created = await self.call(tool, parameters)
        identifier = str(created["id"])
        self.owned_ids.add(identifier)
        analysis = await self.call("analyze_objects", {"id": identifier})
        require(analysis["object_count"] == 1, "Expected exactly one persisted object")
        actual = analysis["analyses"][0]
        metrics = actual["metrics"]
        require(actual["valid"] is True and metrics["is_solid"] is True, "Persisted geometry is not a valid solid")
        require(metrics["naked_edge_count"] == 0, "Persisted geometry contains naked edges")
        require(math.isclose(metrics["volume"], volume, rel_tol=1e-8, abs_tol=1e-6), f"Incorrect volume: {metrics['volume']} != {volume}")
        tolerance = max(float(created["tolerance"]), 1e-6)
        for actual_corner, expected_corner in zip(actual["bounding_box"], bounds):
            for actual_coordinate, expected_coordinate in zip(actual_corner, expected_corner):
                require(abs(actual_coordinate - expected_coordinate) <= tolerance, "Persisted bounding box differs from requested placement")
        return {"created": created, "analysis": actual, "independent_expected_volume": volume, "expected_bounds": bounds}

    async def grasshopper(self) -> dict[str, Any]:
        await self.guard_document()
        state = await self.call("gh_get_document_info")
        if state.get("object_count", 0) != 0:
            raise SkipCheck("Existing Grasshopper objects must not be recomputed by verification")
        self.graph_id = "studio-verification-" + uuid4().hex
        graph = await self.call("gh_build_graph", {
            "graph_id": self.graph_id,
            "components": [
                {"alias": "a", "component_name": "Number Slider", "value": 2, "min": 0, "max": 10, "decimals": 0},
                {"alias": "b", "component_name": "Number Slider", "value": 3, "min": 0, "max": 10, "decimals": 0},
                {"alias": "sum", "component_name": "Addition"},
            ],
            "connections": [
                {"source": "a", "target": "sum", "target_input_index": 0},
                {"source": "b", "target": "sum", "target_input_index": 1},
            ],
            "recompute": True, "rollback_on_error": True, "open_canvas": False,
        })
        self.graph_component_ids = set(graph["aliases"].values())
        value = await self.call("gh_get_parameter_value", {"instance_id": graph["aliases"]["sum"], "max_items": 10})
        numbers = [item for branch in value["values"] for item in branch["items"]]
        require(numbers == [5] and value["data_count"] == 1, f"Grasshopper sum is not 5: {value}")
        return {"graph_id": self.graph_id, "component_count": graph["component_count"], "output": value}

    async def cleanup(self) -> dict[str, Any]:
        removed: dict[str, Any] = {}
        errors = []
        if self.graph_id is not None:
            try:
                current = await self.call("gh_get_graph", {"graph_id": self.graph_id})
                visible_ids = {
                    item["instance_id"]
                    for key in ("components", "standalone_parameters")
                    for item in current.get(key, [])
                }
                require(self.graph_component_ids <= visible_ids, "The active Grasshopper document no longer contains the known test graph; cleanup stopped")
                removed["graph"] = await self.call("gh_clear_graph", {"graph_id": self.graph_id, "recompute": False})
                graph = await self.call("gh_get_graph", {"graph_id": self.graph_id})
                require(graph["object_count"] == 0, "Private verification graph still contains objects")
                self.graph_id = None
            except Exception as error:
                errors.append(f"Graph {self.graph_id}: {error}")
        if self.owned_ids:
            try:
                await self.guard_document()
                ids = ", ".join('"' + identifier + '"' for identifier in sorted(self.owned_ids))
                removed["objects"] = await self.script(
                    f"foreach (var text in new[] {{ {ids} }}) {{\n"
                    "var obj = doc.Objects.FindId(Guid.Parse(text));\n"
                    'if (obj != null && !obj.IsDeleted && !doc.Objects.Delete(obj, true, true)) throw new Exception("Could not remove verification object " + text);\n'
                    "}\ndoc.Views.Redraw();\noutput.AppendLine(\"Known verification objects removed\");"
                )
                self.owned_ids.clear()
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("Cleanup incomplete: " + "; ".join(errors))
        return removed

    async def run(self) -> None:
        environment = os.environ.copy()
        environment.update({
            "PYTHONIOENCODING": "utf-8",
            "RHINO_MCP_HOST": self.args.host if self.args.live else "127.0.0.1",
            "RHINO_MCP_PORT": str(self.args.port if self.args.live else 1),
            "RHINO_MCP_TIMEOUT": str(max(10, self.args.timeout - 10)),
        })
        if self.args.installed:
            environment.pop("PYTHONPATH", None)
            working_directory = Path(tempfile.gettempdir()).resolve()
        else:
            environment["PYTHONPATH"] = str(ROOT / "server" / "src")
            working_directory = ROOT / "server"
        if self.args.live:
            environment.update({"RHINO_MCP_VALIDATE": "strict", "RHINO_MCP_REQUIRE_MATCH": "1"})
        self.report["server_working_directory"] = str(working_directory)
        self.report["runtime_settings"] = {
            key: environment.get(key)
            for key in ("RHINO_MCP_VALIDATE", "RHINO_MCP_REQUIRE_MATCH")
        }
        parameters = StdioServerParameters(
            command=self.args.server_python,
            args=["-m", "rhinomcp"],
            env=environment, cwd=working_directory,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=self.args.timeout) as session:
                self.session = session
                await self.check("mcp_initialize_tools_schemas_guidance", self.inspect_surface)
                if not self.args.live:
                    return
                await self.check("plugin_capabilities", self.capabilities)
                await self.check("empty_document_guard", lambda: self.guard_document(empty=True))
                try:
                    await self.check("modeling_safety", self.modeling_safety)
                    openings = [
                        {"offset": 1000, "width": 900, "bottom": 0, "height": 2100},
                        {"offset": 4000, "width": 2000, "bottom": 900, "height": 1200},
                    ]
                    wall = {"start": [0, 0, 0], "end": [10000, 0, 0], "height": 3000, "thickness": 200, "openings": openings}
                    await self.check("wall_with_door_and_window", lambda: self.architectural_solid("create_wall", wall, 5142000000, [[0, -100, 0], [10000, 100, 3000]]))
                    rotated = dict(wall, start=[20000, 10000, 500], end=[26000, 18000, 500])
                    await self.check("rotated_wall", lambda: self.architectural_solid("create_wall", rotated, 5142000000, [[19920, 9940, 500], [26080, 18060, 3500]]))
                    slab = {"outer": [[0, 20000, 1000], [10000, 20000, 1000], [10000, 28000, 1000], [0, 28000, 1000]], "holes": [[[2000, 22000, 1000], [4000, 22000, 1000], [4000, 24000, 1000], [2000, 24000, 1000]]], "thickness": 200}
                    await self.check("slab_with_hole", lambda: self.architectural_solid("create_floor_slab", slab, 15200000000, [[0, 20000, 800], [10000, 28000, 1000]]))
                    await self.check("grasshopper_numeric_graph", self.grasshopper)
                finally:
                    await self.check("cleanup_owned_objects_and_graph", self.cleanup)
                await self.check("document_empty_after_cleanup", lambda: self.guard_document(empty=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Run modeling only in a separate empty active Rhino document")
    parser.add_argument("--installed", action="store_true", help="Use the selected Python runtime's installed package from a neutral directory, without injecting the checkout")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1999)
    parser.add_argument("--server-python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts" / "studio-verification.json")
    args = parser.parse_args()
    verifier = Verification(args)
    exit_code = 0
    try:
        asyncio.run(verifier.run())
    except Exception as error:
        verifier.report["error"] = str(error)
        exit_code = 1
    finally:
        verifier.report.update(
            completed_at=datetime.now(timezone.utc).isoformat(),
            passed=exit_code == 0,
            remaining_known_object_ids=sorted(verifier.owned_ids),
            remaining_graph_id=verifier.graph_id,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(verifier.report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report: {args.report.resolve()}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
