"""Exercise the real owner HTTP service against the plugin's linked .NET client.

Use a dedicated local validation service; this changes its maintenance policies.
No credentials are printed or copied into the report. Policies are resumed in finally.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request


class Admin:
    def __init__(self, url: str, password: str):
        self.url = url
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        page = self.request("/admin/login")
        csrf = re.search(r'name="csrf" value="([0-9a-f]{64})"', page).group(1)
        self.request("/admin/login", {"csrf": csrf, "password": password})

    def request(self, path, fields=None):
        body = urllib.parse.urlencode(fields).encode() if fields is not None else None
        headers = {"Origin": self.url}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        with self.opener.open(urllib.request.Request(self.url + path, data=body, headers=headers), timeout=8) as response:
            return response.read().decode("utf8")

    def policy(self, path, **fields):
        page = self.request("/admin")
        csrf = re.search(r'name="csrf" value="([0-9a-f]{64})"', page).group(1)
        return self.request(path, {"csrf": csrf, **fields})


def enroll(profile, config: Path):
    data = json.dumps({"client_version": "0.6.0", "platform": "windows"}).encode()
    request = urllib.request.Request(profile["service_url"] + "/v1/enroll", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        identity = json.load(response)
    config.write_text(json.dumps({**profile, **identity}), encoding="utf8")
    return identity["installation_id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    profile = json.loads((args.private_dir / "management-server.json").read_text(encoding="utf8"))
    if profile["service_url"] != "http://127.0.0.1:8765" or not profile["allow_insecure_loopback"]:
        raise RuntimeError("This script is limited to the dedicated local validation service")
    config = args.private_dir / "test-installation.json"
    if not config.exists():
        installation = enroll(profile, config)
    else:
        installation = json.loads(config.read_text(encoding="utf8"))["installation_id"]
    admin = Admin(profile["service_url"], (args.private_dir / "administrator-password.txt").read_text(encoding="utf8").strip())
    executable = root / "management-client-tests/bin/Release/net8.0/ManagementClient.Tests.dll"
    checks = []

    def verify(name, allowed, code=None, path=config):
        result = subprocess.run(["dotnet", str(executable), "--live", str(path.resolve()), "create_object"], capture_output=True, text=True, encoding="utf8", timeout=15)
        value = json.loads(result.stdout)
        assert value["allowed"] is allowed and value["dispatchable"] is allowed, value
        if code is not None:
            assert value["code"] == code, value
        assert result.returncode == (0 if allowed else 1)
        checks.append({"name": name, "passed": True, "allowed": allowed, "code": value["code"]})
        print("PASS", name, flush=True)

    try:
        admin.policy("/admin/policy", paused="0", reason="", minimum_version="")
        admin.policy("/admin/version", version="0.6.0", paused="0", reason="")
        admin.policy("/admin/installation", installation_id=installation, paused="0", reason="")
        verify("real_http_rsa_pss_allow", True, "allowed")
        admin.policy("/admin/policy", paused="1", reason="관리 기능 통합 검사", minimum_version="")
        verify("global_pause", False, "maintenance")
        second = args.private_dir / "new-installation.json"
        enroll(profile, second)
        verify("new_identity_still_obeys_global_pause", False, "maintenance", second)
        admin.policy("/admin/policy", paused="0", reason="", minimum_version="")
        verify("global_resume", True, "allowed")
        admin.policy("/admin/version", version="0.6.0", paused="1", reason="버전 수정 검사")
        verify("exact_version_pause", False, "version_paused")
        admin.policy("/admin/version", version="0.6.0", paused="0", reason="")
        verify("version_resume", True, "allowed")
        admin.policy("/admin/policy", paused="0", reason="", minimum_version="0.6.1")
        verify("minimum_version", False, "update_required")
        admin.policy("/admin/policy", paused="0", reason="", minimum_version="")
        admin.policy("/admin/installation", installation_id=installation, paused="1", reason="개별 설치 검사")
        verify("installation_pause", False, "installation_paused")
        admin.policy("/admin/installation", installation_id=installation, paused="0", reason="")
        verify("installation_resume", True, "allowed")
        unreachable = args.private_dir / "unreachable-installation.json"
        values = json.loads(config.read_text(encoding="utf8"))
        values["service_url"] = "http://127.0.0.1:1"
        unreachable.write_text(json.dumps(values), encoding="utf8")
        verify("unreachable_service_fails_closed", False, "unavailable", unreachable)
        verify("configuration_missing_fails_closed", False, "unconfigured", args.private_dir / "does-not-exist.json")
        verify("fresh_approval_after_recovery", True, "allowed")
    finally:
        admin.policy("/admin/policy", paused="0", reason="", minimum_version="")
        admin.policy("/admin/version", version="0.6.0", paused="0", reason="")
        admin.policy("/admin/installation", installation_id=installation, paused="0", reason="")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"scope": "real HTTP + production .NET client code; not native Rhino", "checks": checks}, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"PASS {len(checks)} cross-language integration checks")


if __name__ == "__main__":
    main()
