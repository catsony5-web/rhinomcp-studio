"""Build a versioned Studio ZIP from the locked Python project and Rhino plugin.

Requires Python 3.11+, uv, .NET 8 SDK and Yak (or prebuilt --wheel/--plugin).
This builds artifacts only; it never installs a Rhino plugin or edits Codex.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

from manager import InstallError, load_profile


REPO = Path(__file__).resolve().parent.parent


def run(args: list[str | Path], **kwargs) -> str:
    result = subprocess.run([str(value) for value in args], text=True, encoding="utf-8",
                            stdout=subprocess.PIPE, **kwargs)
    if result.returncode:
        raise RuntimeError(f"Build command failed ({result.returncode}): {args}\n{result.stdout}")
    return result.stdout


def build(args: argparse.Namespace) -> Path:
    if not getattr(args, "management_profile", None):
        raise InstallError("No management server configured. Pass --management-profile PATH with the operator's public server profile.")
    profile = load_profile(Path(args.management_profile).expanduser().resolve())
    project = tomllib.loads((REPO / "server/pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to export the checked-in dependency lock.")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    final = output / f"rhinomcp-studio-{version}.zip"
    if final.exists():
        raise RuntimeError(f"Release already exists; use another output directory: {final}")
    with tempfile.TemporaryDirectory(prefix="studio-build-", dir=output) as work_name:
        work = Path(work_name)
        bundle = work / f"rhinomcp-studio-{version}"
        (bundle / "wheels").mkdir(parents=True)
        (bundle / "plugin").mkdir()
        (bundle / "management-server.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.wheel:
            wheel = Path(args.wheel).resolve()
        else:
            run([uv, "build", "--wheel", "--python", sys.executable, "--out-dir", work / "wheel-build", REPO / "server"])
            wheel, = (work / "wheel-build").glob("*.whl")
        if wheel.name.split("-")[:2] != ["rhinomcp", version]:
            raise RuntimeError(f"Expected the locally built rhinomcp {version} wheel, got {wheel.name}")
        shutil.copy2(wheel, bundle / "wheels" / wheel.name)
        requirements = run([uv, "export", "--locked", "--no-dev", "--no-emit-project", "--format", "requirements-txt", "--project", REPO / "server"])
        (bundle / "requirements.lock").write_text(requirements, encoding="utf-8")
        if args.plugin:
            plugin = Path(args.plugin).resolve()
        else:
            yak = args.yak or shutil.which("yak")
            if not yak:
                raise RuntimeError("Pass --yak with Rhino's Yak executable, or --plugin with a prebuilt .yak.")
            plugin_build = work / "plugin-build"
            run(["dotnet", "build", REPO / "plugin/rhinomcp.csproj", "--configuration", "Release", "--output", plugin_build])
            yak_root = work / "yak-build"
            shutil.copytree(plugin_build, yak_root / "net8.0")
            shutil.copy2(REPO / "plugin/manifest.yml", yak_root / "manifest.yml")
            run([yak, "build", "--platform", "any"], cwd=yak_root)
            plugin, = yak_root.glob("*.yak")
        with zipfile.ZipFile(plugin) as archive:
            manifest_name = next(name for name in archive.namelist() if name in ("manifest.yml", "manifest.yaml"))
            manifest = archive.read(manifest_name).decode("utf-8-sig")
            fields = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip().strip("'\"")
                      for line in manifest.splitlines() if ":" in line and not line.startswith(" ")}
            if fields.get("name") != "rhinomcp-studio" or fields.get("version") != version:
                raise RuntimeError("The Yak name/version does not match this Studio release.")
        shutil.copy2(plugin, bundle / "plugin" / plugin.name)
        for path in (REPO / "distribution").iterdir():
            if path.suffix in (".ps1", ".sh") or path.name == "manager.py":
                shutil.copy2(path, bundle / path.name)
        shutil.copy2(REPO / "docs/INSTALL_KO.md", bundle / "INSTALL_KO.md")
        shutil.copy2(REPO / "docs/DISTRIBUTION_MANAGEMENT_KO.md", bundle / "DISTRIBUTION_MANAGEMENT_KO.md")
        for relative in ("README.md", "LICENSE", "PROVENANCE.md", "docs/INSTALL_KO.md", "docs/ARCHITECTURE_KO.md", "docs/DISTRIBUTION_MANAGEMENT_KO.md", "docs/VALIDATION_KO.md", "docs/RELEASE_KO.md", "management/README_KO.md", "management/RENDER_KO.md"):
            destination = bundle / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relative, destination)
        metadata = {
            "name": "rhinomcp-studio", "version": version,
            "python": "3.12.12", "uv": "0.11.28",
            "wheel": "wheels/" + wheel.name, "plugin": "plugin/" + plugin.name,
            "management_profile": "management-server.json",
            "local_demo_only": profile["allow_insecure_loopback"],
            "sha256": {str(path.relative_to(bundle)).replace(os.sep, "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(bundle.rglob("*")) if path.is_file()},
        }
        (bundle / "bundle.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(final, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(work))
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    final.with_suffix(".zip.sha256").write_text(f"{digest}  {final.name}\n", encoding="ascii")
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(REPO / "dist"))
    parser.add_argument("--wheel", help="A prebuilt local rhinomcp wheel; otherwise build it")
    parser.add_argument("--plugin", help="A prebuilt rhinomcp-studio .yak; otherwise build it")
    parser.add_argument("--yak", help="Yak executable used when building the plugin")
    parser.add_argument("--management-profile", required=True, help="Public management profile JSON; never pass private signing keys or admin credentials")
    print(build(parser.parse_args()))
