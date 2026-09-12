"""Production bootstrap safety and public profile tests without a cloud account."""

import asyncio
from contextlib import closing
import json
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_service import COOKIE, digest, password_hash
from render_start import configuration, main, prepare_app


class RenderStartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "state"
        self.password = "bootstrap-" + secrets.token_hex(12)
        self.environment = {
            "RENDER_EXTERNAL_URL": "https://owner-test.onrender.com",
            "RHINOMCP_STATE_DIR": str(self.state),
            "RHINOMCP_BOOTSTRAP_PASSWORD": self.password,
            "PORT": "10000",
        }

    def test_first_start_initializes_once_and_removes_process_secret(self):
        app, config = prepare_app(self.environment)
        self.assertEqual(config.port, 10000)
        self.assertFalse(app.state.service.insecure)
        self.assertNotIn("RHINOMCP_BOOTSTRAP_PASSWORD", self.environment)
        with app.state.service.db() as db:
            administrator = db.execute("SELECT * FROM admin").fetchone()
        self.assertEqual(administrator["hash"], password_hash(self.password, bytes.fromhex(administrator["salt"])))

    def test_restart_preserves_signing_key_password_policy_and_registration(self):
        app, _ = prepare_app(self.environment)
        original_key = (self.state / "signing-key.pem").read_bytes()
        with app.state.service.db() as db:
            original_admin = tuple(db.execute("SELECT * FROM admin").fetchone())
            db.execute("UPDATE policy SET paused=1, reason='maintenance' WHERE id=1")
            db.execute("INSERT INTO installations VALUES ('test', ?, '0.6.0', 'windows', 1, 1, 1, 'test')",
                       (digest("private-installation-token"),))
        self.environment["RHINOMCP_BOOTSTRAP_PASSWORD"] = "different-password-must-not-replace"
        restarted, _ = prepare_app(self.environment)
        self.assertEqual((self.state / "signing-key.pem").read_bytes(), original_key)
        with restarted.state.service.db() as db:
            self.assertEqual(tuple(db.execute("SELECT * FROM admin").fetchone()), original_admin)
            self.assertEqual(db.execute("SELECT paused FROM policy").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM installations").fetchone()[0], 1)
        self.assertNotIn("RHINOMCP_BOOTSTRAP_PASSWORD", self.environment)

    def test_restart_without_bootstrap_secret_succeeds(self):
        prepare_app(self.environment)
        prepare_app(self.environment)

    def test_empty_state_without_password_is_not_created(self):
        self.environment.pop("RHINOMCP_BOOTSTRAP_PASSWORD")
        with self.assertRaisesRegex(ValueError, "first initialization"):
            prepare_app(self.environment)
        self.assertFalse(self.state.exists())

    def test_partial_state_is_not_replaced(self):
        for filename in ("signing-key.pem", "control.sqlite3", "unexpected.txt"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                marker = state / filename
                marker.write_bytes(b"must-not-change")
                environment = dict(self.environment, RHINOMCP_STATE_DIR=str(state))
                with self.assertRaisesRegex(ValueError, "Incomplete persistent state"):
                    prepare_app(environment)
                self.assertEqual(list(state.iterdir()), [marker])
                self.assertEqual(marker.read_bytes(), b"must-not-change")

    def test_incomplete_database_fails_without_reinitializing(self):
        prepare_app(self.environment)
        key = (self.state / "signing-key.pem").read_bytes()
        with closing(sqlite3.connect(self.state / "control.sqlite3")) as db:
            db.execute("DROP TABLE policy")
            db.commit()
        before = (self.state / "control.sqlite3").read_bytes()
        with self.assertRaisesRegex(ValueError, "Invalid persistent database"):
            prepare_app(self.environment)
        self.assertEqual((self.state / "signing-key.pem").read_bytes(), key)
        self.assertEqual((self.state / "control.sqlite3").read_bytes(), before)

    def test_invalid_configuration_cannot_initialize_state(self):
        for field, values in {
            "RENDER_EXTERNAL_URL": ["", "http://example.com", "https://example.com/path", "https://user@example.com"],
            "PORT": ["0", "65536", "10000\n", "not-a-port"],
            "RHINOMCP_STATE_DIR": ["relative/state"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        prepare_app(dict(self.environment, **{field: value}))
                    self.assertFalse(self.state.exists())

    def test_explicit_https_origin_takes_precedence(self):
        config = configuration(dict(self.environment, RHINOMCP_PUBLIC_URL="https://control.example.com:443/"))
        self.assertEqual(config.public_url, "https://control.example.com")

    def test_public_profile_has_only_pinning_material_and_remains_host_checked(self):
        app, config = prepare_app(self.environment)

        async def request(host, method="GET"):
            events = []
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(event):
                events.append(event)
            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                     "http_version": "1.1", "method": method, "scheme": "https",
                     "path": "/v1/profile", "raw_path": b"/v1/profile", "query_string": b"",
                     "headers": [(b"host", host.encode())], "client": ("203.0.113.1", 1),
                     "server": (host, 443)}
            await app(scope, receive, send)
            status = next(event["status"] for event in events if event["type"] == "http.response.start")
            body = b"".join(event.get("body", b"") for event in events)
            return status, body

        status, body = asyncio.run(request("owner-test.onrender.com"))
        self.assertEqual(status, 200)
        profile = json.loads(body)
        self.assertEqual(set(profile), {"service_url", "public_key_pem", "allow_insecure_loopback"})
        self.assertEqual(profile, app.state.service.profile(config.public_url, False))
        self.assertIn("BEGIN PUBLIC KEY", profile["public_key_pem"])
        for private in (self.password.encode(), (self.state / "signing-key.pem").read_bytes(), COOKIE.encode()):
            self.assertNotIn(private, body)
        self.assertEqual(asyncio.run(request("attacker.example.com"))[0], 400)
        self.assertEqual(asyncio.run(request("owner-test.onrender.com", "POST"))[0], 405)

    def test_main_explicitly_disables_forwarded_header_trust_and_extra_workers(self):
        with patch("render_start.os.environ", self.environment), patch("uvicorn.run") as run:
            main()
        self.assertEqual(run.call_args.kwargs["host"], "0.0.0.0")
        self.assertEqual(run.call_args.kwargs["port"], 10000)
        self.assertEqual(run.call_args.kwargs["workers"], 1)
        self.assertIs(run.call_args.kwargs["proxy_headers"], False)


if __name__ == "__main__":
    unittest.main()
