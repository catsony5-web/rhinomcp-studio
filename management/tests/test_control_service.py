"""Real HTTP integration tests, with stdlib client and ephemeral private state."""

import base64
import asyncio
import copy
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import uvicorn
from starlette.requests import Request as StarletteRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_service import Service, create_app, digest, initialize, validate_url


PASSWORD = "local-test-" + secrets.token_hex(12)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(NoRedirect, HTTPCookieProcessor(self.cookies))

    def request(self, path, data=None, *, form=False, headers=None):
        headers = dict(headers or {})
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
            data = (urlencode(data) if form else json.dumps(data)).encode("utf-8")
        req = Request(self.base + path, data=data, headers=headers)
        try:
            response = self.opener.open(req, timeout=8)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read().decode("utf-8")


class ControlServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.state = Path(cls.temporary.name) / "state"
        initialize(cls.state, PASSWORD)
        cls.service = Service(cls.state, True)
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.sock.getsockname()[1]}"
        cls.app = create_app(cls.state, True, cls.base)
        cls.server = uvicorn.Server(uvicorn.Config(cls.app, log_level="critical", access_log=False, proxy_headers=False))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.sock]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(.02)
        if not cls.server.started:
            raise RuntimeError("Test service failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.sock.close()
        cls.temporary.cleanup()

    def setUp(self):
        with self.service.db() as db:
            db.execute("UPDATE policy SET paused=0, reason='', minimum_version='' WHERE id=1")
            for table in ("versions", "installations", "sessions", "attempts", "audit"):
                db.execute("DELETE FROM " + table)
        self.client = Client(self.base)

    def login(self, client=None):
        client = client or self.client
        status, _, body = client.request("/admin/login")
        self.assertEqual(status, 200)
        csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', body).group(1)
        status, headers, _ = client.request("/admin/login", {"csrf": csrf, "password": PASSWORD}, form=True)
        self.assertEqual(status, 303)
        status, _, body = client.request("/admin")
        self.assertEqual(status, 200)
        return re.search(r'name="csrf" value="([0-9a-f]+)"', body).group(1), headers

    def enroll(self, version="0.6.0", platform="windows"):
        status, _, body = self.client.request("/v1/enroll", {"client_version": version, "platform": platform})
        self.assertEqual(status, 201)
        return json.loads(body)

    def authorize(self, registration, version="0.6.0", command="create_object", nonce=None):
        data = {"installation_id": registration["installation_id"], "version": version,
                "command": command, "nonce": nonce or secrets.token_hex(32)}
        status, headers, body = self.client.request("/v1/authorize", data,
                   headers={"Authorization": "Bearer " + registration["installation_token"]})
        self.assertEqual(status, 200, body)
        envelope = json.loads(body)
        self.assertEqual(set(envelope), {"payload", "signature"})
        raw = base64.b64decode(envelope["payload"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
        self.service.key.public_key().verify(signature, raw,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        payload = json.loads(raw)
        self.assertEqual(set(payload), {"protocol", "installation_id", "version", "command", "nonce", "allowed", "code", "reason", "issued_at", "expires_at"})
        for key in data:
            self.assertEqual(payload[key], data[key])
        self.assertEqual(payload["protocol"], 1)
        self.assertIs(type(payload["allowed"]), bool)
        self.assertEqual(payload["expires_at"], payload["issued_at"] + 30)
        self.assertLessEqual(abs(payload["issued_at"] - time.time()), 3)
        self.assertEqual(headers["Cache-Control"], "no-store")
        return payload, raw, signature

    def policy(self, csrf, paused, reason="", minimum=""):
        result = self.client.request("/admin/policy", {"csrf": csrf, "paused": str(paused),
                         "reason": reason, "minimum_version": minimum}, form=True)
        self.assertEqual(result[0], 303, result[2])

    def test_enroll_authorize_and_hashed_credentials(self):
        registration = self.enroll()
        payload, _, _ = self.authorize(registration)
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["code"], "allowed")
        with self.service.db() as db:
            record = db.execute("SELECT * FROM installations").fetchone()
            self.assertEqual(record["token_hash"], digest(registration["installation_token"]))
            self.assertNotIn(registration["installation_token"], repr(tuple(record)))
        self.assertNotIn(registration["installation_token"].encode(), (self.state / "control.sqlite3").read_bytes())

    def test_pause_resume_applies_to_current_and_new_installations(self):
        first = self.enroll()
        csrf, _ = self.login()
        self.policy(csrf, 1, "오류 수정 중")
        for registration in (first, self.enroll(platform="macos")):
            payload, _, _ = self.authorize(registration)
            self.assertFalse(payload["allowed"])
            self.assertEqual(payload["code"], "maintenance")
            self.assertEqual(payload["reason"], "오류 수정 중")
        self.policy(csrf, 0)
        self.assertTrue(self.authorize(first)[0]["allowed"])

    def test_exact_version_and_minimum_version(self):
        registration = self.enroll()
        csrf, _ = self.login()
        self.assertEqual(self.client.request("/admin/version", {"csrf": csrf, "version": "0.6.0", "paused": "1", "reason": "버전 오류"}, form=True)[0], 303)
        self.assertEqual(self.authorize(registration)[0]["code"], "version_paused")
        self.assertTrue(self.authorize(registration, "0.6.1")[0]["allowed"])
        self.assertEqual(self.client.request("/admin/version", {"csrf": csrf, "version": "0.6.0", "paused": "0", "reason": "수정 완료"}, form=True)[0], 303)
        self.assertTrue(self.authorize(registration)[0]["allowed"])
        self.policy(csrf, 0, minimum="0.10.0")
        self.assertEqual(self.authorize(registration, "0.9.9")[0]["code"], "update_required")
        self.assertTrue(self.authorize(registration, "0.10.0")[0]["allowed"])

    def test_installation_pause_and_persistence(self):
        registration = self.enroll()
        other = self.enroll()
        csrf, _ = self.login()
        for paused, expected in (("1", "installation_paused"), ("0", "allowed")):
            self.assertEqual(self.client.request("/admin/installation", {"csrf": csrf, "installation_id": registration["installation_id"], "paused": paused, "reason": "지원 확인"}, form=True)[0], 303)
            self.assertEqual(self.authorize(registration)[0]["code"], expected)
            self.assertTrue(self.authorize(other)[0]["allowed"])
        reopened = Service(self.state)
        with reopened.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM installations").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action LIKE 'installation_%'").fetchone()[0], 2)

    def test_invalid_installation_and_separate_admin_auth(self):
        registration = self.enroll()
        forged = dict(registration, installation_token=secrets.token_hex(32))
        data = {"installation_id": forged["installation_id"], "version": "0.6.0", "command": "create_object", "nonce": secrets.token_hex(32)}
        self.assertEqual(self.client.request("/v1/authorize", data, headers={"Authorization": "Bearer " + forged["installation_token"]})[0], 401)
        self.assertEqual(self.client.request("/admin/policy", {"paused": "1", "reason": "x", "csrf": "x"}, form=True,
                       headers={"Authorization": "Bearer " + registration["installation_token"]})[0], 401)
        self.login()
        self.assertEqual(self.client.request("/v1/authorize", data)[0], 401)

    def test_nonce_command_and_version_are_signature_bound(self):
        registration = self.enroll()
        first, raw, signature = self.authorize(registration)
        second, _, _ = self.authorize(registration)
        self.assertNotEqual(first["nonce"], second["nonce"])
        for field in ("nonce", "command", "version", "installation_id", "allowed", "expires_at"):
            changed = copy.copy(first)
            changed[field] = "different" if field not in ("allowed", "expires_at") else False if field == "allowed" else 0
            with self.assertRaises(InvalidSignature):
                self.service.key.public_key().verify(signature, json.dumps(changed, ensure_ascii=False, separators=(",", ":")).encode(),
                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())

    def test_csrf_required_for_each_admin_mutation_and_logout(self):
        registration = self.enroll()
        csrf, _ = self.login()
        cases = {"/admin/policy": {"paused": "1", "reason": "x", "minimum_version": ""},
                 "/admin/version": {"version": "0.6.0", "paused": "1", "reason": "x"},
                 "/admin/installation": {"installation_id": registration["installation_id"], "paused": "1", "reason": "x"},
                 "/admin/logout": {}}
        for path, data in cases.items():
            self.assertEqual(self.client.request(path, dict(data, csrf="forged"), form=True)[0], 403)
        self.assertTrue(self.authorize(registration)[0]["allowed"])
        self.assertEqual(self.client.request("/admin/logout", {"csrf": csrf}, form=True)[0], 303)
        self.assertEqual(self.client.request("/admin")[0], 303)
        self.assertEqual(self.client.request("/admin/policy", dict(cases["/admin/policy"], csrf=csrf), form=True)[0], 401)

    def test_login_csrf_and_throttle(self):
        self.assertEqual(self.client.request("/admin/login", {"password": PASSWORD, "csrf": "forged"}, form=True)[0], 403)
        _, _, body = self.client.request("/admin/login")
        csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', body).group(1)
        for _ in range(4):
            self.assertEqual(self.client.request("/admin/login", {"password": "wrong-password-value", "csrf": csrf}, form=True)[0], 401)
        self.assertEqual(self.client.request("/admin/login", {"password": PASSWORD, "csrf": csrf}, form=True)[0], 429)

    def test_html_escaped_no_secrets_and_security_headers(self):
        registration = self.enroll()
        csrf, headers = self.login()
        cookie = headers.get_all("set-cookie")[0]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.policy(csrf, 1, '<script>alert("unsafe")</script>')
        _, headers, body = self.client.request("/admin")
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn(registration["installation_token"], body)
        self.assertNotIn(PASSWORD, body)
        self.assertNotIn("PRIVATE KEY", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        payload, _, _ = self.authorize(registration)
        with self.service.db() as db:
            rows = db.execute("SELECT * FROM audit").fetchall()
            self.assertNotIn(PASSWORD, repr([tuple(r) for r in rows]))
        self.assertNotIn(payload["nonce"].encode(), (self.state / "control.sqlite3").read_bytes())

    def test_host_and_origin_are_validated(self):
        self.assertEqual(self.client.request("/healthz", headers={"Host": "attacker.example"})[0], 400)
        self.assertEqual(self.client.request("/admin/login", headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.client.request("/healthz")[0], 200)

    def test_rejects_bad_requests_and_empty_pause_reason(self):
        self.assertEqual(self.client.request("/v1/enroll", {"client_version": "../1", "platform": "windows"})[0], 400)
        self.assertEqual(self.client.request("/v1/enroll", {"client_version": "0.6.0", "platform": "windows", "extra": "x"})[0], 400)
        self.assertEqual(self.client.request("/v1/enroll", {"client_version": "x" * 9000, "platform": "windows"})[0], 413)
        csrf, _ = self.login()
        self.assertEqual(self.client.request("/admin/policy", {"csrf": csrf, "paused": "1", "reason": "", "minimum_version": ""}, form=True)[0], 400)

    def test_profile_has_only_public_information_and_url_rules(self):
        profile = self.service.profile("https://control.example.com", False)
        self.assertEqual(set(profile), {"service_url", "public_key_pem", "allow_insecure_loopback"})
        self.assertIn("BEGIN PUBLIC KEY", profile["public_key_pem"])
        self.assertNotIn("PRIVATE", json.dumps(profile))
        for url, insecure in (("http://control.example.com", False), ("http://control.example.com", True),
                              ("http://127.0.0.1.evil.example", True), ("https://user:pass@control.example.com", False),
                              ("https://control.example.com/path", False), ("https://control.example.com?q=x", False)):
            with self.assertRaises(ValueError):
                validate_url(url, insecure)
        self.assertEqual(validate_url("http://127.0.0.1:8765/", True), "http://127.0.0.1:8765")
        self.assertEqual(validate_url("https://CONTROL.example.com:443/", False), "https://control.example.com")
        with self.assertRaises(ValueError):
            validate_url("https://control.example.com\n", False)
        with self.assertRaises(ValueError):
            create_app(self.state, False)

    def test_initializer_never_overwrites_state(self):
        before = (self.state / "signing-key.pem").read_bytes()
        with self.assertRaises(ValueError):
            initialize(self.state, PASSWORD)
        self.assertEqual(before, (self.state / "signing-key.pem").read_bytes())

    def test_production_session_cookie_is_secure(self):
        service = Service(self.state, False)
        csrf = secrets.token_hex(32)
        body = urlencode({"csrf": csrf, "password": PASSWORD}).encode()
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request = StarletteRequest({"type": "http", "method": "POST", "path": "/admin/login",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded"),
                        (b"cookie", ("rhino_login_csrf=" + csrf).encode())],
            "client": ("127.0.0.1", 12345)}, receive)
        response = asyncio.run(service.login(request))
        cookie = response.headers.getlist("set-cookie")[0]
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)


if __name__ == "__main__":
    unittest.main()
