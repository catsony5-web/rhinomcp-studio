"""Live export/capture/Undo verification in an otherwise empty Rhino document.

Run this file with the INSTALLED Studio venv Python, for example:
  <Studio root>/releases/<version>/venv/Scripts/python.exe scripts/verify_exports.py

This is an explicit live test: do not edit or switch the Rhino document while it
runs. It creates two solids and one isolated Undo probe, exports only its known
GUIDs, and finally removes only those GUIDs if the original document is active.
It never clears a document, resets Undo history, or saves the active document.
Dimensions and expected volumes are expressed in the active document's units.
Each run creates a new output directory containing report.json, a PNG, and a 3dm.
An ambiguous failed mutation is not retried; an unacknowledged GUID is not guessed.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
from typing import Any, Callable
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parents[1]
ENUMERATOR = """
var scan = new Rhino.DocObjects.ObjectEnumeratorSettings {
    NormalObjects = true, LockedObjects = true, HiddenObjects = true,
    ActiveObjects = true, ReferenceObjects = true, IdefObjects = true,
    IncludeLights = true, IncludeGrips = true, DeletedObjects = false
};
var active = doc.Objects.GetObjectList(scan).ToArray();
"""
SERIALIZER = """
string Serialize(object value) {
    var type = AppDomain.CurrentDomain.GetAssemblies()
        .Select(a => a.GetType("Newtonsoft.Json.JsonConvert"))
        .First(t => t != null);
    return (string)type.GetMethod("SerializeObject", new[] { typeof(object) })
        .Invoke(null, new[] { value });
}
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def cs_string(value: str) -> str:
    """JSON basic string escaping is compatible with a C# string literal."""
    return json.dumps(value, ensure_ascii=True)


def guid_array(identifiers: set[str]) -> str:
    values = ", ".join(f"new Guid({cs_string(str(UUID(value)))})" for value in sorted(identifiers))
    return "new Guid[] { " + values + " }"


class ExportVerification:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.run_id = uuid4().hex
        self.output = Path(args.output_dir).expanduser().resolve() if args.output_dir else (
            ROOT / "artifacts" / ("exports-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + self.run_id[:8])
        )
        self.output.mkdir(parents=True, exist_ok=False)
        self.connection = None
        self.serial: int | None = None
        self.owned: set[str] = set()
        self.expected_volumes: dict[str, float] = {}
        self.report: dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "server_python": sys.executable,
            "output_directory": str(self.output),
            "checks": [],
            "ambiguous_mutations": [],
            "limitations": [
                "This helper tests the live local Rhino process, not every platform.",
                "PNG signature/dimensions are verified; visual appearance requires human review.",
                "Do not edit or switch documents during the isolated Undo/Redo sequence.",
            ],
        }

    def check(self, name: str, operation: Callable[[], Any]) -> Any:
        item: dict[str, Any] = {"name": name}
        self.report["checks"].append(item)
        started = time.monotonic()
        try:
            result = operation()
            item.update(status="passed", details=result)
            return result
        except Exception as error:
            item.update(status="failed", error=str(error))
            raise
        finally:
            item["duration_seconds"] = round(time.monotonic() - started, 3)

    def call(self, command: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.connection.send_command(command, parameters or {})
        require(isinstance(result, dict), f"Unexpected {command} response")
        require(result.get("success") is not False, f"{command}: {result.get('message', result)}")
        return result

    def script(self, code: str) -> Any:
        result = self.call("execute_rhinocommon_csharp_code", {"code": SERIALIZER + code})
        require(result.get("success") is True, "C# verification did not succeed")
        return json.loads(result.get("output", "").strip())

    def serial_guard(self) -> str:
        code = 'if (doc == null) throw new Exception("No active Rhino document");\n'
        if self.serial is not None:
            code += f'if (doc.RuntimeSerialNumber != {self.serial}u) throw new Exception("Active Rhino document changed; no further operation allowed");\n'
        return code

    def snapshot(self, expected: set[str] | None = None) -> dict[str, Any]:
        code = self.serial_guard() + ENUMERATOR
        if expected is not None:
            code += (
                f"var expected = new HashSet<Guid>({guid_array(expected)});\n"
                'if (!expected.SetEquals(active.Select(o => o.Id))) throw new Exception("Active document object IDs differ from the exact owned set");\n'
            )
        code += """
output.AppendLine(Serialize(new {
    serial = doc.RuntimeSerialNumber, units = doc.ModelUnitSystem.ToString(),
    tolerance = doc.ModelAbsoluteTolerance, path = doc.Path,
    ids = active.Select(o => o.Id.ToString()).OrderBy(id => id).ToArray(),
    undo_enabled = doc.UndoRecordingEnabled,
    current_layer_visible = doc.Layers.CurrentLayer.IsVisible,
    current_layer_locked = doc.Layers.CurrentLayer.IsLocked
}));
"""
        result = self.script(code)
        if self.serial is None:
            self.serial = int(result["serial"])
            self.report["document_serial"] = self.serial
        require(int(result["serial"]) == self.serial, "Document serial changed")
        return result

    def connect(self) -> dict[str, Any]:
        # Configure before importing server.py, whose connection settings are globals.
        os.environ.update({
            "RHINO_MCP_HOST": "127.0.0.1", "RHINO_MCP_PORT": str(self.args.port),
            "RHINO_MCP_TIMEOUT": str(self.args.timeout), "RHINO_MCP_VALIDATE": "strict",
            "RHINO_MCP_REQUIRE_MATCH": "1", "RHINO_MCP_PERCEPTION": "1",
        })
        import rhinomcp
        from rhinomcp.server import RhinoConnection

        installed_path = Path(rhinomcp.__file__).resolve()
        require(installed_path.is_relative_to(Path(sys.prefix).resolve()),
                "Use the installed Studio venv Python; editable/source imports are not accepted")
        version = metadata.version("rhinomcp")
        if self.args.expected_version is not None:
            require(version == self.args.expected_version, f"Installed server is {version}, expected {self.args.expected_version}")
        self.connection = RhinoConnection("127.0.0.1", self.args.port)
        capabilities = self.call("describe_capabilities")
        plugin_version = str(capabilities.get("version", ""))
        require(plugin_version.split(".")[:3] == version.split(".")[:3],
                f"Live plugin {plugin_version!r} does not match installed server {version}")
        self.report["installed_package"] = str(installed_path)
        self.report["capabilities"] = capabilities
        return {"package": str(installed_path), "server_version": version, "plugin_version": plugin_version}

    def initial_document(self) -> dict[str, Any]:
        result = self.snapshot(set())
        require(result["undo_enabled"] is True, "Undo recording must already be enabled; no settings were changed")
        require(result["current_layer_visible"] is True and result["current_layer_locked"] is False,
                "Use a visible, unlocked current layer for this capture test")
        return result

    def create(self, command: str, parameters: dict[str, Any], expected_volume: float | None = None) -> dict[str, Any]:
        self.snapshot(self.owned)
        parameters = dict(parameters, name="StudioExportVerification_" + self.run_id + "_" + command)
        try:
            result = self.call(command, parameters)
        except Exception as error:
            self.report["ambiguous_mutations"].append({"command": command, "name": parameters["name"], "error": str(error)})
            raise
        # Record acknowledged ownership before any validation that could fail.
        identifier = str(UUID(str(result["id"])))
        self.owned.add(identifier)
        self.report["acknowledged_ids"] = sorted(self.owned)
        if expected_volume is not None:
            self.expected_volumes[identifier] = expected_volume
            require(result.get("geometry_health", {}).get("is_solid") is True, "Created result is not a verified solid")
            require(math.isclose(float(result["volume"]), expected_volume, rel_tol=1e-8, abs_tol=1e-6),
                    f"Created volume {result.get('volume')} differs from expected {expected_volume}")
        return result

    def create_solids(self) -> dict[str, Any]:
        wall = self.create("create_wall", {
            "start": [0, 0, 0], "end": [6000, 0, 0], "height": 3000, "thickness": 200,
            "openings": [{"offset": 800, "width": 900, "bottom": 0, "height": 2100},
                         {"offset": 3000, "width": 1500, "bottom": 900, "height": 1200}],
        }, 2862000000.0)
        slab = self.create("create_floor_slab", {
            "outer": [[0, 1000, 0], [6000, 1000, 0], [6000, 5000, 0], [0, 5000, 0]],
            "holes": [[[1000, 2000, 0], [2000, 2000, 0], [2000, 3000, 0], [1000, 3000, 0]]],
            "thickness": 200,
        }, 4600000000.0)
        self.snapshot(self.owned)
        return {"wall": wall, "slab": slab}

    def capture(self) -> dict[str, Any]:
        self.snapshot(self.owned)
        result = self.call("capture_viewport", {
            "viewport": "perspective", "width": 1200, "height": 900,
            "show_grid": False, "show_axes": True, "show_cplane_axes": False, "zoom_to_fit": True,
        })
        png = base64.b64decode(result["image_data"], validate=True)
        require(png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 32, "Capture is not a PNG")
        require(png[12:16] == b"IHDR", "PNG has no initial IHDR chunk")
        width, height = struct.unpack(">II", png[16:24])
        require((width, height) == (1200, 900), "PNG dimensions differ from requested capture")
        path = self.output / "architecture-preview.png"
        path.write_bytes(png)
        self.snapshot(self.owned)
        return {"path": str(path), "bytes": len(png), "sha256": hashlib.sha256(png).hexdigest(),
                "width": width, "height": height, "viewport": result.get("viewport_name"), "visual_review": "pending"}

    def export_and_readback(self) -> dict[str, Any]:
        require(set(self.expected_volumes) == self.owned and len(self.owned) == 2, "Export requires exactly the two known architectural solids")
        path = self.output / "architecture-sample.3dm"
        pairs = ",\n".join(
            "{ new Guid(" + cs_string(identifier) + "), " + repr(volume) + " }"
            for identifier, volume in sorted(self.expected_volumes.items())
        )
        code = self.serial_guard() + ENUMERATOR + f"""
var expected = new Dictionary<Guid, double> {{ {pairs} }};
if (!new HashSet<Guid>(expected.Keys).SetEquals(active.Select(o => o.Id)))
    throw new Exception("Document changed before export");
var targetPath = {cs_string(str(path))};
if (System.IO.File.Exists(targetPath)) throw new Exception("Refusing to overwrite an export");
var savedIds = new Dictionary<Guid, double>();
using (var model = new Rhino.FileIO.File3dm()) {{
    model.Settings.ModelUnitSystem = doc.ModelUnitSystem;
    model.Settings.ModelAbsoluteTolerance = doc.ModelAbsoluteTolerance;
    var exportLayer = new Layer {{ Id = Guid.NewGuid(), Name = "Studio export verification" }};
    model.AllLayers.Add(exportLayer);
    var savedLayer = model.AllLayers.FindId(exportLayer.Id);
    if (savedLayer == null) throw new Exception("Could not add the export layer");
    var layerIndex = savedLayer.Index;
    foreach (var pair in expected) {{
        var obj = doc.Objects.FindId(pair.Key);
        var brep = obj?.Geometry as Brep;
        if (obj == null || obj.IsDeleted || brep == null || !brep.IsValid || !brep.IsSolid)
            throw new Exception("Known export object is missing or not a valid solid");
        var attributes = obj.Attributes.Duplicate();
        attributes.LayerIndex = layerIndex;
        var savedId = model.Objects.AddBrep(brep, attributes);
        if (savedId == Guid.Empty) throw new Exception("Could not add known solid to File3dm");
        savedIds.Add(savedId, pair.Value);
    }}
    if (!model.Write(targetPath, 8)) throw new Exception("File3dm.Write failed");
}}
var rows = new List<object>();
using (var saved = Rhino.FileIO.File3dm.Read(targetPath)) {{
    if (saved == null || saved.Objects.Count != expected.Count) throw new Exception("Saved model object count differs");
    if (saved.Settings.ModelUnitSystem != doc.ModelUnitSystem) throw new Exception("Saved model units differ");
    foreach (var obj in saved.Objects) {{
        var brep = obj.Geometry as Brep;
        if (!savedIds.ContainsKey(obj.Attributes.ObjectId) || brep == null || !brep.IsValid || !brep.IsSolid)
            throw new Exception("Saved model includes unknown or invalid geometry");
        using (var mass = VolumeMassProperties.Compute(brep)) {{
            var volume = mass?.Volume ?? double.NaN;
            var expectedVolume = savedIds[obj.Attributes.ObjectId];
            if (!double.IsFinite(volume) || Math.Abs(volume - expectedVolume) > Math.Max(1e-6, expectedVolume * 1e-8))
                throw new Exception("Read-back solid volume differs from dimensions");
            rows.Add(new {{ id = obj.Attributes.ObjectId.ToString(), name = obj.Attributes.Name,
                is_valid = brep.IsValid, is_solid = brep.IsSolid, volume, expected_volume = expectedVolume }});
        }}
    }}
    output.AppendLine(Serialize(new {{ path = targetPath, object_count = saved.Objects.Count,
        units = saved.Settings.ModelUnitSystem.ToString(), format_version_requested = 8, objects = rows }}));
}}
"""
        result = self.script(code)
        require(path.is_file() and path.stat().st_size > 0, "Rhino did not produce an accessible nonempty 3dm")
        result["bytes"] = path.stat().st_size
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.snapshot(self.owned)
        return result

    def object_ids(self, expected: set[str]) -> dict[str, Any]:
        """Only read-only get_objects is used inside the isolated Undo/Redo sequence."""
        result = self.call("get_objects", {"offset": 0, "limit": 200, "include_geometry": False})
        ids = {str(UUID(str(item["id"]))) for item in result["objects"]}
        require(result.get("has_more") is False and int(result["total_matching"]) == len(ids), "Object listing is incomplete")
        require(ids == expected, f"Object IDs differ; expected {sorted(expected)}, got {sorted(ids)}")
        return result

    def undo_redo(self) -> dict[str, Any]:
        before = set(self.owned)
        self.snapshot(before)
        # create() does its final serial/exact-set guard BEFORE the typed mutation.
        probe = self.create("create_object", {
            "type": "BOX", "params": {"width": 100, "length": 100, "height": 100},
            "translation": [9000, 9000, 50],
        })
        identifier = str(UUID(str(probe["id"])))
        # No C# script, capture, export, attribute edit or cleanup between these calls.
        # Read-only object queries cannot become the top Undo record or clear Redo.
        created_state = self.object_ids(self.owned)
        undone = self.call("undo", {"steps": 1})
        require(undone.get("undone_steps") == 1, "Undo did not undo exactly one operation")
        undone_state = self.object_ids(before)
        redone = self.call("redo", {"steps": 1})
        require(redone.get("redone_steps") == 1, "Redo did not redo exactly one operation")
        redone_state = self.object_ids(self.owned)
        final = self.snapshot(self.owned)
        return {"probe_id": identifier, "created": created_state, "undo": undone,
                "after_undo": undone_state, "redo": redone, "after_redo": redone_state,
                "final_document_serial": final["serial"], "script_calls_between_create_and_redo": 0}

    def cleanup(self) -> dict[str, Any]:
        if not self.owned or self.serial is None:
            return {"removed_ids": [], "note": "No acknowledged live object IDs to clean up"}
        # Serial validation and exact-ID deletion happen within one UI-thread script.
        # A changed document stops all deletion; no broad object enumeration is deleted.
        code = self.serial_guard() + f"""
var known = {guid_array(self.owned)};
var removed = new List<string>();
var absent = new List<string>();
var failed = new List<string>();
foreach (var id in known) {{
    var obj = doc.Objects.FindId(id);
    if (obj == null || obj.IsDeleted) {{ absent.Add(id.ToString()); continue; }}
    if (doc.Objects.Delete(obj, true, true)) removed.Add(id.ToString());
    else failed.Add(id.ToString());
}}
doc.Views.Redraw();
{ENUMERATOR}
output.AppendLine(Serialize(new {{ removed_ids = removed, already_absent_ids = absent,
    failed_ids = failed, remaining_ids = active.Select(o => o.Id.ToString()).OrderBy(id => id).ToArray(),
    serial = doc.RuntimeSerialNumber }}));
"""
        result = self.script(code)
        self.report["cleanup_result"] = result
        require(not result["failed_ids"], f"Could not delete owned IDs: {result['failed_ids']}")
        require(not (self.owned & set(result["remaining_ids"])), "Known verification geometry remains")
        self.owned.clear()
        require(not result["remaining_ids"], "Unexpected objects remain; they were preserved instead of guessed as owned")
        return result

    def run(self) -> int:
        failed = False
        try:
            self.check("installed_server_and_plugin", self.connect)
            self.check("empty_document_all_objects_and_serial", self.initial_document)
            self.check("wall_and_slab", self.create_solids)
            self.check("viewport_png", self.capture)
            self.check("file3dm_export_and_readback", self.export_and_readback)
            self.check("isolated_undo_redo", self.undo_redo)
        except Exception as error:
            failed = True
            self.report["error"] = str(error)
        finally:
            try:
                self.check("cleanup_exact_owned_ids", self.cleanup)
            except Exception as error:
                failed = True
                self.report["cleanup_error"] = str(error)
                self.report["unremoved_acknowledged_ids"] = sorted(self.owned)
            if self.connection is not None:
                self.connection.disconnect()
            self.report["status"] = "failed" if failed else "passed"
            self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
            (self.output / "report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": self.report["status"], "report": str(self.output / "report.json"),
                          "sample": str(self.output / "architecture-sample.3dm"),
                          "preview": str(self.output / "architecture-preview.png")}, ensure_ascii=False))
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="New, nonexisting directory for this run's artifacts")
    parser.add_argument("--port", type=int, default=1999)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--expected-version", help="Optional exact version; otherwise require the live plugin to match the installed server")
    args = parser.parse_args()
    require(0 < args.port < 65536, "Port must be between 1 and 65535")
    require(math.isfinite(args.timeout) and args.timeout > 0, "Timeout must be finite and positive")
    return ExportVerification(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
