"""Check a public Studio ZIP before uploading it; never install or run its files."""

from __future__ import annotations

import argparse
import base64
from email.parser import BytesParser
import hashlib
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import socket
import stat
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

import manager


class ReleaseError(RuntimeError):
    pass


def parse_object(raw: bytes) -> dict:
    """Match the Rhino client's JSON object, duplicate-key and depth checks."""
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseError("Management JSON contains a duplicate field.")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ReleaseError("Management JSON contains an invalid numeric value.")

    result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ReleaseError("Management service did not return a JSON object.")
    pending = [(result, 1)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, (dict, list)):
            if depth > 8:
                raise ReleaseError("Management JSON exceeds the supported nesting depth.")
            pending.extend((child, depth + 1) for child in (value.values() if isinstance(value, dict) else value))
    return result


def public_profile(value: dict, *, resolve: bool = False) -> dict:
    profile = manager.validate_profile(value)
    parsed = urllib.parse.urlsplit(profile["service_url"])
    host = parsed.hostname.rstrip(".").lower()
    if profile["allow_insecure_loopback"] or parsed.scheme != "https":
        raise ReleaseError("A public release requires HTTPS with local demo mode disabled.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None and ("." not in host or host.endswith((".localhost", ".local", ".internal", ".invalid", ".test"))):
        raise ReleaseError("The management server must have a public hostname or IP address.")
    if address is not None and not address.is_global:
        raise ReleaseError("A public release cannot use a private or loopback management address.")
    if resolve:
        addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ReleaseError("The management hostname must resolve only to public addresses.")
    return profile


def verify_release(archive_path: Path, expected_version: str) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+", expected_version):
        raise ReleaseError("Expected version must have the form major.minor.patch.")
    root_name = f"rhinomcp-studio-{expected_version}"
    if archive_path.name != root_name + ".zip":
        raise ReleaseError("ZIP filename does not match the expected release version.")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum = archive_path.with_suffix(".zip.sha256").read_text(encoding="ascii").strip()
    if checksum != f"{digest}  {archive_path.name}":
        raise ReleaseError("ZIP checksum or checksum filename does not match.")
    with tempfile.TemporaryDirectory(prefix="studio-release-check-") as temporary:
        destination = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > 5000 or sum(item.file_size for item in members) > 512 * 1024 * 1024:
                raise ReleaseError("ZIP exceeds the distribution size limit.")
            names = set()
            for item in members:
                path = PurePosixPath(item.filename)
                if ("\\" in item.filename or path.is_absolute() or ".." in path.parts
                        or not path.parts or path.parts[0] != root_name
                        or ":" in item.filename or item.filename.casefold() in names
                        or stat.S_ISLNK(item.external_attr >> 16)):
                    raise ReleaseError("ZIP contains an unsafe or duplicate path.")
                names.add(item.filename.casefold())
                archive.extract(item, destination)
        bundle = destination / root_name
        metadata = manager.verify_bundle(bundle)
        if metadata["version"] != expected_version or metadata.get("local_demo_only") is not False:
            raise ReleaseError("Release version is wrong or the ZIP is marked for a local demo.")
        files = {path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()}
        if set(metadata["sha256"]) != files - {"bundle.json"}:
            raise ReleaseError("Every bundled file must have exactly one recorded checksum.")
        required = {"manager.py", "requirements.lock", "bootstrap.ps1", "bootstrap.sh", "install.ps1",
                    "install.sh", "doctor.ps1", "doctor.sh", "uninstall.ps1", "uninstall.sh",
                    "INSTALL_KO.md", "DISTRIBUTION_MANAGEMENT_KO.md", "LICENSE", "PROVENANCE.md",
                    "README.md", "docs/VALIDATION_KO.md", "management/README_KO.md"}
        if not required <= files:
            raise ReleaseError("Required installer or documentation files are missing.")
        profile = public_profile(manager.load_profile(bundle / metadata["management_profile"]))
        with zipfile.ZipFile(bundle / metadata["wheel"]) as wheel:
            wheel_metadata = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
            if len(wheel_metadata) != 1:
                raise ReleaseError("Wheel must contain exactly one package metadata document.")
            package = BytesParser().parsebytes(wheel.read(wheel_metadata[0]))
            if package["Name"] != "rhinomcp" or package["Version"] != expected_version:
                raise ReleaseError("The Python wheel package version does not match the release.")
        with zipfile.ZipFile(bundle / metadata["plugin"]) as plugin:
            manifests = [name for name in plugin.namelist() if name in ("manifest.yml", "manifest.yaml")]
            if len(manifests) != 1 or "net8.0/rhinomcp.rhp" not in plugin.namelist():
                raise ReleaseError("Yak package must contain one manifest and the Rhino .NET 8 plugin.")
            fields = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip().strip("'\"")
                      for line in plugin.read(manifests[0]).decode("utf-8-sig").splitlines()
                      if ":" in line and not line.startswith(" ")}
            if fields.get("name") != "rhinomcp-studio" or fields.get("version") != expected_version:
                raise ReleaseError("The Yak package version does not match the release.")
    return {"version": expected_version, "sha256": digest, "profile": profile}


def request_json(url: str, data: dict | None = None, token: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode("utf-8"), headers=headers)
    with urllib.request.build_opener(manager.NoRedirect()).open(request, timeout=5) as response:
        raw = response.read(manager.MAX_MANAGEMENT_BYTES + 1)
        if response.status not in (200, 201) or len(raw) > manager.MAX_MANAGEMENT_BYTES:
            raise ReleaseError("Management service returned an invalid or oversized response.")
        return parse_object(raw)


def check_service(profile: dict, version: str) -> None:
    # Only the release operator needs cryptography; it is not an installer dependency.
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    profile = public_profile(profile, resolve=True)
    origin = profile["service_url"]
    if request_json(origin + "/healthz") != {"status": "ok", "protocol": 1}:
        raise ReleaseError("Management service health or protocol is incompatible.")
    enrollment = request_json(origin + "/v1/enroll", {"client_version": version, "platform": "windows"})
    if set(enrollment) != {"installation_id", "installation_token"}:
        raise ReleaseError("Management enrollment returned invalid registration fields.")
    registration = manager.validate_registration(dict(profile, **enrollment))
    started_at = int(time.time())
    started_timestamp = time.monotonic()
    request = {"installation_id": registration["installation_id"], "version": version,
               "command": "get_document_summary", "nonce": secrets.token_hex(32)}
    response = request_json(origin + "/v1/authorize", request, registration["installation_token"])
    if set(response) != {"payload", "signature"}:
        raise ReleaseError("Management authorization response is invalid.")
    payload = base64.b64decode(response["payload"], validate=True)
    signature = base64.b64decode(response["signature"], validate=True)
    key = serialization.load_pem_public_key(profile["public_key_pem"].encode("ascii"))
    key.verify(signature, payload, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
    grant = parse_object(payload)
    now = int(time.time())
    reason = grant.get("reason")
    if (type(grant.get("protocol")) is not int or grant["protocol"] != 1
            or any(grant.get(name) != value for name, value in request.items())
            or grant.get("allowed") is not True or grant.get("code") != "allowed"
            or not isinstance(reason, str) or len(reason.encode("utf-16-le")) > 2048 * 2
            or type(grant.get("issued_at")) is not int or type(grant.get("expires_at")) is not int
            or not -(2 ** 63) <= grant["issued_at"] <= 2 ** 63 - 1 - 30
            or not -(2 ** 63) <= grant["expires_at"] <= 2 ** 63 - 1
            or grant["expires_at"] != grant["issued_at"] + 30
            or not started_at - 5 <= grant["issued_at"] <= now + 5
            or now >= grant["expires_at"] or time.monotonic() - started_timestamp >= 30):
        raise ReleaseError("The management service did not issue a fresh, bound approval for this version.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--check-service", action="store_true", help="Require live HTTPS enrollment and signed authorization")
    args = parser.parse_args()
    try:
        report = verify_release(args.archive, args.expected_version)
        if args.check_service:
            check_service(report["profile"], report["version"])
        print(json.dumps({"version": report["version"], "sha256": report["sha256"],
                          "service_url": report["profile"]["service_url"], "service_checked": args.check_service}))
        return 0
    except Exception as exc:
        # Network exceptions can contain response details; never print credentials or server bodies.
        message = str(exc) if isinstance(exc, (ReleaseError, manager.InstallError)) else type(exc).__name__
        print("Public release verification failed: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
