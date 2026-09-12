"""Install, diagnose and remove RhinoMCP Studio without changing global Python.

Only this application's directory and its named Codex MCP table are owned here.
Rhino's Yak CLI owns the plugin files. No Rhino process is killed by this script.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone


NAME = "rhino-studio"
PACKAGE = "rhinomcp-studio"
MARKER = ".rhinomcp-studio-root"
MARKER_TEXT = "RhinoMCP Studio managed installation\n"
PLUGIN_GUID = "f0b5b632-cc3c-43e7-bc88-da29c47b98bc"
PROFILE_FIELDS = {"service_url", "public_key_pem", "allow_insecure_loopback"}
REGISTRATION_FIELDS = PROFILE_FIELDS | {"installation_id", "installation_token"}
MAX_MANAGEMENT_BYTES = 16384


class InstallError(RuntimeError):
    pass


def validate_public_key(value: object) -> str:
    """Accept only a DER SPKI RSA public key with a 3072 to 8192-bit modulus."""
    if not isinstance(value, str) or len(value) > MAX_MANAGEMENT_BYTES:
        raise InstallError("Management public_key_pem must be an RSA public key PEM.")
    match = re.fullmatch(r"\s*-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\s]+)-----END PUBLIC KEY-----\s*", value)
    if not match:
        raise InstallError("Management profile needs a PUBLIC KEY PEM, never a private signing key.")
    try:
        der = base64.b64decode(re.sub(r"\s", "", match[1]), validate=True)
        def field(data: bytes, offset: int, tag: int) -> tuple[bytes, int]:
            if offset + 2 > len(data) or data[offset] != tag:
                raise ValueError("Invalid DER tag")
            length = data[offset + 1]
            start = offset + 2
            if length & 128:
                count = length & 127
                if not 1 <= count <= 4 or start + count > len(data):
                    raise ValueError("Invalid DER length")
                length = int.from_bytes(data[start:start + count], "big")
                start += count
            end = start + length
            if end > len(data):
                raise ValueError("Truncated DER")
            return data[start:end], end
        outer, end = field(der, 0, 0x30)
        algorithm, offset = field(outer, 0, 0x30)
        bits, finish = field(outer, offset, 0x03)
        if end != len(der) or finish != len(outer) or algorithm != bytes.fromhex("06092a864886f70d0101010500") or bits[:1] != b"\0":
            raise ValueError("Expected RSA SPKI")
        rsa, end = field(bits, 1, 0x30)
        modulus, offset = field(rsa, 0, 0x02)
        exponent, finish = field(rsa, offset, 0x02)
        if end != len(bits) or finish != len(rsa) or not modulus or modulus[0] & 128 or not 3072 <= int.from_bytes(modulus, "big").bit_length() <= 8192 or int.from_bytes(exponent, "big") < 3:
            raise ValueError("Invalid RSA public parameters")
    except (ValueError, IndexError) as exc:
        raise InstallError("Management public key must be a valid RSA SPKI PEM with 3072 to 8192 bits.") from exc
    return value.strip() + "\n"


def validate_profile(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != PROFILE_FIELDS:
        raise InstallError("Management profile must contain only service_url, public_key_pem and allow_insecure_loopback. Never include private keys, admin passwords or installation tokens.")
    url = value["service_url"]
    local = value["allow_insecure_loopback"]
    if not isinstance(url, str) or not url or len(url) > 2048 or any(char.isspace() or ord(char) < 32 for char in url) or type(local) is not bool:
        raise InstallError("Invalid management service URL or allow_insecure_loopback flag.")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise InstallError("Invalid management service URL.") from exc
    if not parsed.hostname or parsed.username is not None or parsed.password is not None or "?" in url or "#" in url or "\\" in url or parsed.path not in ("", "/") or (port is not None and port == 0):
        raise InstallError("Management service URL must be an origin with no path, credentials, query or fragment.")
    is_loopback = parsed.hostname in ("127.0.0.1", "::1", "localhost")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local and is_loopback):
        raise InstallError("Management requires HTTPS. HTTP is allowed only for an explicitly enabled localhost, 127.0.0.1 or ::1 local demo.")
    if local and not is_loopback:
        raise InstallError("allow_insecure_loopback may be enabled only for an exact loopback address.")
    return {"service_url": url.rstrip("/"), "public_key_pem": validate_public_key(value["public_key_pem"]), "allow_insecure_loopback": local}


def load_profile(path: Path) -> dict:
    if not path.is_file():
        raise InstallError("No management server configured. Obtain a public management profile from the operator and build with --management-profile PATH; an unmanaged release cannot be installed.")
    if path.stat().st_size > MAX_MANAGEMENT_BYTES:
        raise InstallError("Management profile is too large.")
    return validate_profile(json.loads(path.read_text(encoding="utf-8")))


def management_path() -> Path:
    return default_root() / "management.json"


def validate_registration(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != REGISTRATION_FIELDS:
        raise InstallError("Invalid installed management registration; it was preserved. Restore its original credentials instead of registering a new identity.")
    profile = validate_profile({key: value[key] for key in PROFILE_FIELDS})
    try:
        installation_id = str(uuid.UUID(value["installation_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise InstallError("Invalid management installation ID.") from exc
    token = value["installation_token"]
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise InstallError("Invalid management installation token.")
    return dict(profile, installation_id=installation_id, installation_token=token)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def enroll(profile: dict, version: str) -> dict:
    if sys.platform not in ("win32", "darwin"):
        raise InstallError("Registration supports Windows and macOS only.")
    payload = json.dumps({"client_version": version, "platform": "windows" if sys.platform == "win32" else "macos"}).encode("utf-8")
    request = urllib.request.Request(profile["service_url"] + "/v1/enroll", data=payload,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=5) as response:
            if response.status not in (200, 201):
                raise InstallError("Management enrollment did not return success; installation was stopped.")
            raw = response.read(MAX_MANAGEMENT_BYTES + 1)
            if len(raw) > MAX_MANAGEMENT_BYTES:
                raise InstallError("Management enrollment response is too large.")
            result = json.loads(raw)
        if not isinstance(result, dict) or set(result) != {"installation_id", "installation_token"}:
            raise InstallError("Management enrollment returned an invalid registration.")
        return validate_registration(dict(profile, **result))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # Do not echo a response body, token, or exception URL into logs.
        raise InstallError("Management server registration failed. Check the configured server and internet connection; there is no offline installation fallback.") from exc


def prepare_registration(profile: dict, version: str, state: dict, root: Path, allow_change: bool) -> tuple[Path, str, str]:
    path = management_path().absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            raise InstallError("Management registration path cannot use a symlink/junction.")
    previous = read_text(path)
    owned = state.get("management")
    if owned:
        if owned.get("path") != str(path) or not previous or hashlib.sha256(previous.encode("utf-8")).hexdigest() != owned.get("sha256"):
            raise InstallError("Installed management registration is missing or changed. Restore the original file; registration was not reset.")
        registration = validate_registration(json.loads(previous))
        old_profile = {key: registration[key] for key in PROFILE_FIELDS}
        if old_profile == profile:
            return path, previous, previous
        if not allow_change:
            raise InstallError("Management service or public key changed. Confirm the new operator, then rerun with --change-management-service.")
    elif path.exists():
        raise InstallError("The fixed per-user management registration belongs to another installation. Use its original InstallRoot; the existing registration was preserved.")
    # A custom root must not add files to a different managed root.
    if path.parent != root and (path.parent / "state.json").exists():
        raise InstallError("The per-user management directory is owned by another Studio installation. Use that installation's original InstallRoot.")
    registration = enroll(profile, version)
    return path, previous, json.dumps(registration, ensure_ascii=False, indent=2) + "\n"


def default_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "RhinoMCPStudio"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/RhinoMCPStudio"
    raise InstallError("Supported systems: Windows x64 and macOS (Intel/Apple Silicon).")


def checked_root(value: Path) -> Path:
    root = value.expanduser().absolute()
    if root == Path(root.anchor) or root == Path.home() or len(root.parts) < 3:
        raise InstallError(f"Unsafe installation directory: {root}")
    for parent in (root, *root.parents):
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            raise InstallError(f"Installation directory cannot use a symlink/junction: {parent}")
    if root.exists() and any(root.iterdir()):
        marker = root / MARKER
        if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_TEXT:
            raise InstallError(f"Refusing to use a non-Studio directory: {root}")
    return root


def inside(root: Path, value: Path) -> Path:
    root = root.resolve()
    resolved = value.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise InstallError(f"Path is outside the managed installation: {value}")
    return resolved


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig") if path.exists() else ""


def target_config(content: str) -> dict | None:
    try:
        return tomllib.loads(content).get("mcp_servers", {}).get(NAME)
    except (tomllib.TOMLDecodeError, AttributeError) as exc:
        raise InstallError(f"Codex config is not valid TOML: {exc}") from exc


def _header_path(line: str) -> tuple[str, ...] | None:
    if not line.lstrip().startswith("["):
        return None
    try:
        document = tomllib.loads(line + "\n__studio_table_probe__ = true\n")
    except tomllib.TOMLDecodeError:
        return None
    path = []
    value = document
    while isinstance(value, dict) and "__studio_table_probe__" not in value:
        if len(value) != 1:
            return None
        key, value = next(iter(value.items()))
        path.append(key)
        if isinstance(value, list):
            value = value[0]
    return tuple(path)


def without_target(content: str) -> str:
    """Remove only the named server's ordinary TOML tables, preserving other text."""
    lines = content.splitlines(keepends=True)
    kept = []
    dropping = False
    found = False
    for index, line in enumerate(lines):
        path = _header_path(line)
        if path is not None:
            try:
                # A header-looking line inside a multiline TOML value is data.
                tomllib.loads("".join(lines[:index]))
            except tomllib.TOMLDecodeError:
                path = None
        if path is not None:
            dropping = path[:2] == ("mcp_servers", NAME)
            found |= dropping
        if not dropping:
            kept.append(line)
    if target_config(content) is not None and not found:
        raise InstallError(
            "rhino-studio is defined in an inline TOML table. Move that entry to "
            "[mcp_servers.rhino-studio] before installing/removing; other settings were preserved."
        )
    result = "".join(kept)
    expected = tomllib.loads(content)
    expected.get("mcp_servers", {}).pop(NAME, None)
    actual = tomllib.loads(result)
    # Removing the final server table can also remove its now-empty parent.
    for values in (expected, actual):
        if values.get("mcp_servers") == {}:
            values.pop("mcp_servers")
    if actual != expected:
        raise InstallError("Refusing a config edit that would change settings outside rhino-studio.")
    return result


def config_block(settings: dict) -> str:
    # JSON strings use escaping compatible with TOML basic strings.
    def q(value):
        return json.dumps(value, ensure_ascii=False)
    lines = [f"[mcp_servers.{NAME}]"]
    for key, value in settings.items():
        if key == "env":
            continue
        lines.append(f"{key} = {q(value)}")
    lines.extend(["", f"[mcp_servers.{NAME}.env]"])
    lines.extend(f"{key} = {q(value)}" for key, value in settings["env"].items())
    return "\n".join(lines) + "\n"


def replace_config(content: str, settings: dict) -> str:
    preserved = without_target(content)
    separator = "" if not preserved or preserved.endswith("\n\n") else ("\n" if preserved.endswith("\n") else "\n\n")
    result = preserved + separator + config_block(settings)
    if target_config(result) != settings:
        raise InstallError("Could not safely construct the Codex MCP configuration.")
    return result


def run(command: list[str | Path], *, env: dict | None = None, cwd: Path | None = None) -> str:
    result = subprocess.run([str(item) for item in command], text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    if result.returncode:
        raise InstallError(f"Command failed ({result.returncode}): {command[0]}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def locate_yak(rhino_path: str | None) -> Path:
    if rhino_path:
        base = Path(rhino_path).expanduser()
        choices = [base, base / "System/yak.exe", base / "Contents/Resources/bin/yak"]
    elif sys.platform == "win32":
        choices = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Rhino 8/System/yak.exe"]
    else:
        choices = [Path("/Applications/Rhino 8.app/Contents/Resources/bin/yak")]
    for path in choices:
        if path.is_file() and path.name in ("yak", "yak.exe"):
            return path.resolve()
    raise InstallError("Rhino 8 was not found. Use --rhino-path with its installation folder (or yak executable).")


def require_rhino_closed() -> None:
    if sys.platform == "win32":
        output = run(["tasklist", "/FI", "IMAGENAME eq Rhino.exe", "/FO", "CSV", "/NH"])
        running = '"rhino.exe"' in output.lower()
    else:
        output = run(["ps", "-axo", "comm="])
        running = any("Rhino 8.app/Contents/MacOS/" in line for line in output.splitlines())
    if running:
        raise InstallError("Save your work and close Rhino before installing, updating or uninstalling the plugin.")


def require_supported_rhino(yak: Path) -> str:
    if sys.platform == "win32":
        import winreg
        executable = yak.parent / "Rhino.exe"
        quoted = str(executable).replace("'", "''")
        version = run(["powershell.exe", "-NoProfile", "-Command", f"(Get-Item -LiteralPath '{quoted}').VersionInfo.FileVersion"])
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\McNeel\Rhinoceros\8.0\Global Options") as key:
                runtime, _ = winreg.QueryValueEx(key, "DotNetRuntime")
                if str(runtime).lower() == "netfx":
                    raise InstallError("Rhino is configured for .NET Framework. Review other plugin compatibility, then use SetDotNetRuntime to choose .NET 8 and restart Rhino.")
        except FileNotFoundError:
            pass
    else:
        with (yak.parents[2] / "Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        version = str(info.get("CFBundleShortVersionString", info.get("CFBundleVersion", "")))
    match = re.search(r"(\d+)\.(\d+)", version)
    if not match or int(match[1]) != 8 or int(match[2]) < 20:
        raise InstallError(f"Studio requires Rhino 8.20 or later in the Rhino 8 series; found {version!r}.")
    return version


def installed_packages(yak: Path) -> dict[str, str]:
    result = {}
    for line in run([yak, "list"]).splitlines():
        match = re.match(r"^\s*([a-zA-Z0-9_-]+)\s+(?:\()?([0-9]+\.[^\s)]+)", line)
        if match:
            result[match[1].lower()] = match[2]
    return result


def manual_upstream_plugin(yak: Path) -> list[str]:
    """Detect the shared GUID when the original plugin was installed without Yak."""
    if sys.platform == "win32":
        import winreg
        key = rf"Software\McNeel\Rhinoceros\8.0\Plug-ins\{PLUGIN_GUID}"
        paths = []
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    for name in ("FileName", "FolderName"):
                        try:
                            value, _ = winreg.QueryValueEx(handle, name)
                            if value and "rhinomcp-studio" not in str(value).lower():
                                paths.append(str(value))
                        except FileNotFoundError:
                            pass
            except FileNotFoundError:
                pass
        return paths
    plugin_dir = Path.home() / "Library/Application Support/McNeel/Rhinoceros/8.0/Plug-ins"
    if not plugin_dir.exists():
        return []
    return [str(path) for path in plugin_dir.rglob("rhinomcp.rhp")]


def verify_bundle(bundle: Path) -> dict:
    manifest = bundle / "bundle.json"
    if not manifest.is_file():
        raise InstallError("This is a source checkout, not a release ZIP. Build a distribution first (distribution/build.py).")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("name") != PACKAGE or not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)", metadata.get("version", "")):
        raise InstallError("Invalid Studio release metadata.")
    for relative, expected in metadata["sha256"].items():
        path = inside(bundle, bundle / relative)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise InstallError(f"Release checksum mismatch: {relative}")
    for key, prefix in (("wheel", "wheels/"), ("plugin", "plugin/")):
        value = metadata.get(key, "")
        if not value.startswith(prefix) or value not in metadata["sha256"]:
            raise InstallError(f"Release metadata does not include a verified {key}.")
    if "requirements.lock" not in metadata["sha256"]:
        raise InstallError("Release is missing its verified dependency lock.")
    if metadata.get("management_profile") != "management-server.json" or "management-server.json" not in metadata["sha256"]:
        raise InstallError("No management server configured in this release. Rebuild with --management-profile PATH.")
    load_profile(bundle / "management-server.json")
    return metadata


def load_state(root: Path) -> dict:
    path = root / "state.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("name") != PACKAGE:
        raise InstallError("Unexpected installation state; no changes were made.")
    return data


def server_settings(python: Path) -> dict:
    return {
        "command": str(python), "args": ["-m", "rhinomcp"],
        "startup_timeout_sec": 30, "tool_timeout_sec": 120,
        "env": {"RHINO_MCP_HOST": "127.0.0.1", "RHINO_MCP_PORT": "1999",
                "RHINO_MCP_TIMEOUT": "60", "RHINO_MCP_PERCEPTION": "1",
                "RHINO_MCP_VALIDATE": "strict", "PYTHONUTF8": "1", "RHINO_MCP_REQUIRE_MATCH": "1"},
    }


def install(args: argparse.Namespace) -> None:
    root = checked_root(args.install_root)
    bundle = Path(args.bundle).resolve()
    metadata = verify_bundle(bundle)
    yak = locate_yak(args.rhino_path)
    require_supported_rhino(yak)
    require_rhino_closed()
    packages = installed_packages(yak)
    state = load_state(root)
    if PACKAGE in packages and not state:
        raise InstallError("A Studio Yak package is already installed, but this InstallRoot does not own it. Use the original InstallRoot, or remove that installation with its own uninstaller first.")
    if "rhinomcp" in packages and not args.replace_upstream:
        raise InstallError("The original rhinomcp Yak package shares this plugin's GUID. Review removal, then rerun with --replace-upstream.")
    if "rhinomcp" not in packages:
        manual = manual_upstream_plugin(yak)
        if manual:
            raise InstallError("A manually installed rhinomcp plugin was found. Disable/remove it in Rhino PlugInManager first:\n" + "\n".join(manual))
    config = Path(args.codex_config).expanduser().absolute()
    before = read_text(config)
    existing = target_config(before)
    if existing is not None and existing != state.get("settings"):
        raise InstallError("The Codex name rhino-studio is already in use or was edited after installation. Rename that entry before proceeding.")
    profile = load_profile(bundle / metadata["management_profile"])
    registration_path, registration_before, registration_after = prepare_registration(
        profile, metadata["version"], state, root, getattr(args, "change_management_service", False))
    state_before = read_text(root / "state.json")
    root.mkdir(parents=True, exist_ok=True)
    write_atomic(root / MARKER, MARKER_TEXT)
    version = metadata["version"]
    release = inside(root, root / "releases" / version)
    env_path = release / "venv"
    python = env_path / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if release.exists() and state.get("version") != version:
        raise InstallError(f"A previous/incomplete release exists: {release}. Keep it for recovery or remove that release folder before retrying.")
    uv = Path(args.uv).resolve()
    env = dict(os.environ, UV_CACHE_DIR=str(root / "cache"), UV_NO_CONFIG="1", UV_PYTHON_DOWNLOADS="never")
    same_release = state.get("version") == version and state.get("bundle") == metadata
    if state.get("version") == version and not same_release:
        raise InstallError("This version was already installed from different release contents. Build a new version; do not overwrite a published release.")
    if same_release:
        if not python.is_file():
            raise InstallError("The installed Python environment is incomplete. Uninstall Studio and reinstall this ZIP to repair it.")
        run([python, "-c", "from importlib.metadata import version; import rhinomcp.server; "
             f"assert version('rhinomcp') == {version!r}"], env=env)
    if not same_release:
        release.mkdir(parents=True)
        try:
            run([uv, "venv", "--python", sys.executable, env_path], env=env)
            wheel = bundle / metadata["wheel"]
            requirements = read_text(bundle / "requirements.lock")
            requirements += f"\n{wheel.as_uri()} --hash=sha256:{metadata['sha256'][metadata['wheel']]}\n"
            requirement_path = release / "requirements.lock"
            write_atomic(requirement_path, requirements)
            run([uv, "pip", "sync", "--python", python, "--require-hashes", "--no-build", "--strict",
                 "--find-links", bundle / "wheels", requirement_path], env=env)
            run([python, "-c", "from importlib.metadata import version; import rhinomcp.server; "
                 f"assert version('rhinomcp') == {version!r}; print('MCP imports verified')"], env=env)
            shutil.copy2(bundle / metadata["plugin"], release / Path(metadata["plugin"]).name)
        except BaseException:
            shutil.rmtree(inside(root, release))
            raise
    settings = server_settings(python)
    after = replace_config(before, settings)
    backup = root / "backups" / ("config-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".toml")
    write_atomic(backup, before)
    plugin_changed = False
    upstream_removed = False
    state_after = ""
    try:
        if read_text(registration_path) != registration_before:
            raise InstallError("Management registration changed during installation; retry with its owning installer.")
        write_atomic(registration_path, registration_after)
        if "rhinomcp" in packages:
            run([yak, "uninstall", "rhinomcp"])
            upstream_removed = True
        if packages.get(PACKAGE) != version:
            run([yak, "install", bundle / metadata["plugin"]])
            plugin_changed = True
        # Recheck the exact file: don't clobber a concurrent user/Codex edit.
        if read_text(config) != before:
            raise InstallError("Codex config changed during installation. Retry after its settings are saved.")
        write_atomic(config, after)
        new_state = {"name": PACKAGE, "version": version, "bundle": metadata, "settings": settings,
                     "config": str(config), "yak": str(yak), "release": str(release),
                     "previous_version": state.get("version"), "backup": str(backup),
                     "management": {"path": str(registration_path), "sha256": hashlib.sha256(registration_after.encode("utf-8")).hexdigest()}}
        state_after = json.dumps(new_state, ensure_ascii=False, indent=2) + "\n"
        write_atomic(root / "state.json", state_after)
    except BaseException as original:
        recovery_errors = []
        for path, expected, previous in ((config, after, before), (registration_path, registration_after, registration_before),
                                         (root / "state.json", state_after, state_before)):
            try:
                if expected and read_text(path) == expected:
                    if previous:
                        write_atomic(path, previous)
                    else:
                        path.unlink(missing_ok=True)
            except OSError:
                recovery_errors.append(f"Could not restore {path.name}; restore the previous installation before retrying.")
        if plugin_changed:
            try:
                run([yak, "uninstall", PACKAGE])
                if state.get("release"):
                    old_release = inside(root, Path(state["release"]))
                    old_plugins = list(old_release.glob("*.yak"))
                    if len(old_plugins) == 1:
                        run([yak, "install", old_plugins[0]])
            except InstallError as exc:
                recovery_errors.append(str(exc))
        if upstream_removed:
            try:
                run([yak, "install", "rhinomcp", packages["rhinomcp"]])
            except InstallError as exc:
                recovery_errors.append(str(exc))
        if not same_release:
            shutil.rmtree(inside(root, release))
        if recovery_errors:
            raise InstallError(f"{original}\nRecovery needs attention:\n" + "\n".join(recovery_errors)) from original
        raise
    print(f"Installed RhinoMCP Studio {version}. Open Rhino, then restart/reconnect Codex MCP.")
    print(f"Codex server: {NAME}\nConfig backup: {backup}\nRun doctor after Rhino starts to verify the live bridge.")


def bridge_status(command: str = "describe_capabilities") -> dict:
    if command not in ("describe_capabilities", "get_management_status"):
        raise InstallError("Unsupported read-only diagnostic command.")
    payload = json.dumps({"type": command, "params": {}}).encode()
    def receive(connection: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise InstallError("Rhino closed the diagnostic connection.")
            data.extend(chunk)
        return bytes(data)
    with socket.create_connection(("127.0.0.1", 1999), timeout=5) as connection:
        connection.sendall(struct.pack(">I", len(payload)) + payload)
        length = struct.unpack(">I", receive(connection, 4))[0]
        if not 0 < length < 4 * 1024 * 1024:
            raise InstallError("Port 1999 did not return a supported RhinoMCP response.")
        response = json.loads(receive(connection, length))
        if response.get("status") != "success":
            raise InstallError("Rhino diagnostic failed; check the plugin's status in Rhino.")
        return response.get("result", {})


def doctor(args: argparse.Namespace) -> None:
    root = checked_root(args.install_root)
    state = load_state(root)
    if not state:
        raise InstallError("RhinoMCP Studio is not installed. Run install first.")
    config = Path(state["config"])
    checks = {"installation": str(root), "version": state["version"],
              "codex_config_matches": target_config(read_text(config)) == state["settings"],
              "python_exists": Path(state["settings"]["command"]).is_file(),
              "management_registration_matches": False}
    registration = None
    registration_token = None
    try:
        path = management_path().absolute()
        registration_text = read_text(path)
        registration = validate_registration(json.loads(registration_text))
        registration_token = registration["installation_token"]
        ownership = state.get("management", {})
        checks["management_registered"] = ownership.get("path") == str(path) and ownership.get("sha256") == hashlib.sha256(registration_text.encode("utf-8")).hexdigest()
        checks["management_service"] = registration["service_url"]
        checks["management_local_demo"] = registration["allow_insecure_loopback"]
    except (InstallError, OSError, ValueError):
        checks["management_registered"] = False
        checks["management_error"] = "Management registration is missing or invalid. Restore its original credentials; do not reset registration."
    try:
        checks["yak_packages"] = installed_packages(Path(state["yak"]))
        checks["plugin_installed"] = checks["yak_packages"].get(PACKAGE) == state["version"]
    except InstallError as exc:
        checks["plugin_installed"] = False
        checks["yak_error"] = str(exc)
    if checks["python_exists"]:
        try:
            checks["server_import"] = run([state["settings"]["command"], "-c", "import rhinomcp.server; print('ok')"]) == "ok"
        except InstallError as exc:
            checks["server_import"] = False
            checks["server_error"] = str(exc)
    try:
        capabilities = bridge_status()
        checks["bridge_version"] = capabilities.get("version")
        reported = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(capabilities.get("version", "")))
        checks["bridge_matches"] = bool(reported and ".".join(reported.groups()) == state["version"])
        checks["commands"] = len(capabilities.get("commands", []))
        management = bridge_status("get_management_status")
        # Explicit allowlist: never dump arbitrary plugin payloads or credentials.
        checks["management_status"] = {key: management[key] for key in (
            "configured", "state", "reason", "installation_id", "last_checked_at", "service_url", "version") if key in management}
        checks["management_status_available"] = True
        checks["management_registration_matches"] = bool(
            registration and management.get("configured") is True
            and management.get("installation_id") == registration["installation_id"]
            and management.get("service_url") == registration["service_url"])
    except (InstallError, OSError, ValueError) as exc:
        checks["bridge_matches"] = False
        checks["bridge_error"] = str(exc)
    diagnostic = json.dumps(checks, ensure_ascii=False, indent=2)
    if registration_token:
        diagnostic = diagnostic.replace(registration_token, "[redacted]")
    print(diagnostic)
    if not all(checks.get(key) for key in ("codex_config_matches", "python_exists", "plugin_installed", "server_import", "bridge_matches", "management_registered", "management_status_available", "management_registration_matches")):
        raise InstallError("Diagnosis needs attention. Start Rhino and run StudioMCPStart if the bridge is unavailable, then retry.")


def uninstall(args: argparse.Namespace) -> None:
    root = checked_root(args.install_root)
    state = load_state(root)
    if not state:
        print("No active Studio installation was found.")
        return
    require_rhino_closed()
    config = Path(state["config"])
    before = read_text(config)
    existing = target_config(before)
    if existing is not None and existing != state["settings"]:
        raise InstallError("The rhino-studio Codex entry was modified. Remove/rename that entry before uninstalling; its executable has been preserved.")
    after = without_target(before) if existing is not None else before
    registration_path = management_path().absolute()
    registration_before = read_text(registration_path)
    ownership = state.get("management")
    if ownership:
        if ownership.get("path") != str(registration_path) or (registration_path.exists() and ownership.get("sha256") != hashlib.sha256(registration_before.encode("utf-8")).hexdigest()):
            raise InstallError("Management registration was modified or belongs to another installation; it was preserved. Restore the owned registration before uninstalling.")
    elif registration_path.parent == root and registration_path.exists():
        raise InstallError("An unrelated management registration is present in this installation directory; removal was stopped to preserve it.")
    packages = installed_packages(Path(state["yak"]))
    if PACKAGE in packages and packages[PACKAGE] != state["version"]:
        raise InstallError("The Studio Yak package was updated outside this installation. Use its matching installer to remove it; the current package and Codex settings were preserved.")
    if PACKAGE in packages:
        run([state["yak"], "uninstall", PACKAGE])
    if read_text(config) != before:
        raise InstallError("Codex config changed during removal. Retry to safely finish removal.")
    if ownership and read_text(registration_path) != registration_before:
        raise InstallError("Management registration changed during removal; it was preserved. Retry after its settings are saved.")
    if after != before:
        write_atomic(config, after)
    if ownership:
        registration_path.unlink(missing_ok=True)
    (root / "state.json").unlink()
    print("Studio plugin and its Codex MCP entry removed. The launcher will remove the private runtime after Python exits.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "doctor", "uninstall"])
    parser.add_argument("--install-root", type=Path, default=None)
    parser.add_argument("--bundle", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--uv", default=shutil.which("uv") or "uv")
    parser.add_argument("--rhino-path")
    parser.add_argument("--codex-config", default=str(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"))
    parser.add_argument("--replace-upstream", action="store_true")
    parser.add_argument("--change-management-service", action="store_true", help="Explicitly approve a different management server or signing public key")
    args = parser.parse_args()
    try:
        args.install_root = args.install_root or default_root()
        {"install": install, "doctor": doctor, "uninstall": uninstall}[args.action](args)
        return 0
    except (InstallError, OSError, ValueError) as exc:
        print(f"RhinoMCP Studio: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
