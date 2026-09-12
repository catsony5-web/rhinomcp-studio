"""RhinoMCP Studio owner-operated authorization service (single SQLite node)."""

from __future__ import annotations

import argparse
import base64
from contextlib import closing, contextmanager
import getpass
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route


VERSION = re.compile(r"(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})\Z")
COMMAND = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
NONCE = re.compile(r"[0-9a-fA-F]{64}\Z")
COOKIE = "rhino_admin_session"
MAX_BODY = 8192
SESSION_SECONDS = 8 * 3600


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=32768, r=8, p=1,
                          maxmem=128 * 1024 * 1024).hex()


def valid_version(value: object) -> bool:
    return isinstance(value, str) and VERSION.fullmatch(value) is not None


def validate_url(url: str, insecure: bool) -> str:
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise ValueError("Service URL contains invalid characters")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid service URL") from exc
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("Service URL must be an origin without credentials, query or path")
    if insecure:
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("Development HTTP is allowed only on exact loopback hosts")
    elif parsed.scheme != "https":
        raise ValueError("Production service URL requires HTTPS")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    suffix = f":{port}" if port is not None and port != (443 if parsed.scheme == "https" else 80) else ""
    return f"{parsed.scheme}://{host}{suffix}"


def initialize(state: Path, password: str) -> None:
    if len(password) < 14 or len(password) > 1024:
        raise ValueError("Administrator password must contain 14 to 1024 characters")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(state.iterdir()):
        raise ValueError("Initialization requires an empty state directory; existing state is never replaced")
    os.chmod(state, 0o700)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    key_path = state / "signing-key.pem"
    with key_path.open("xb") as file:
        file.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    os.chmod(key_path, 0o600)
    salt = secrets.token_bytes(32)
    with closing(sqlite3.connect(state / "control.sqlite3")) as db:
        db.executescript("""
            CREATE TABLE admin (id INTEGER PRIMARY KEY CHECK(id=1), salt TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE policy (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL,
                                 reason TEXT NOT NULL, minimum_version TEXT NOT NULL);
            CREATE TABLE versions (version TEXT PRIMARY KEY, paused INTEGER NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE installations (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                version TEXT NOT NULL, platform TEXT NOT NULL, created_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL, paused INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '');
            CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires_at INTEGER NOT NULL);
            CREATE TABLE attempts (kind TEXT NOT NULL, subject TEXT NOT NULL, at INTEGER NOT NULL);
            CREATE INDEX attempts_lookup ON attempts(kind, subject, at);
            CREATE TABLE audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
                                action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL);
        """)
        db.execute("INSERT INTO admin VALUES (1, ?, ?)", (salt.hex(), password_hash(password, salt)))
        db.execute("INSERT INTO policy VALUES (1, 0, '', '')")
        db.execute("INSERT INTO audit(at, action, target, detail) VALUES (?, 'initialize', 'service', '')",
                   (int(time.time()),))
        db.commit()
    os.chmod(state / "control.sqlite3", 0o600)


class Service:
    def __init__(self, state: Path, insecure_loopback: bool = False):
        self.state = state.resolve()
        self.insecure = insecure_loopback
        if not (self.state / "control.sqlite3").is_file():
            raise ValueError("Initialize the state directory before serving")
        self.key = serialization.load_pem_private_key((self.state / "signing-key.pem").read_bytes(), None)
        if not isinstance(self.key, rsa.RSAPrivateKey) or self.key.key_size < 3072:
            raise ValueError("Signing key must be RSA with at least 3072 bits")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.state / "control.sqlite3", timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def profile(self, url: str, insecure: bool) -> dict:
        return {
            "service_url": validate_url(url, insecure),
            "public_key_pem": self.key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii"),
            "allow_insecure_loopback": insecure,
        }

    def audit(self, db, action: str, target: str = "", detail: str = ""):
        db.execute("INSERT INTO audit(at, action, target, detail) VALUES (?, ?, ?, ?)",
                   (int(time.time()), action, target, detail))

    async def body(self, request: Request) -> bytes:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BODY:
                raise HTTPException(413, "Request too large")
        return bytes(data)

    async def json_body(self, request: Request, keys: set[str]) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise HTTPException(415, "JSON required")
        try:
            data = json.loads(await self.body(request))
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(data, dict) or set(data) != keys or any(not isinstance(v, str) for v in data.values()):
            raise HTTPException(400, "Invalid request fields")
        return data

    async def form(self, request: Request) -> dict[str, str]:
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise HTTPException(415, "URL-encoded form required")
        try:
            values = parse_qs((await self.body(request)).decode("utf-8"), keep_blank_values=True,
                              max_num_fields=12, strict_parsing=True)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Invalid form")
        if any(len(v) != 1 for v in values.values()):
            raise HTTPException(400, "Duplicate form field")
        return {key: value[0] for key, value in values.items()}

    def throttle(self, request: Request, kind: str, limit: int, window: int, global_limit: int) -> bool:
        subject = digest(request.client.host if request.client else "unknown")
        now = int(time.time())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE at < ?", (now - 3600,))
            row = db.execute("SELECT count(*) AS total, sum(subject=?) AS own FROM attempts WHERE kind=? AND at>?",
                             (subject, kind, now - window)).fetchone()
            blocked = row["total"] >= global_limit or (row["own"] or 0) >= limit
            if not blocked:
                db.execute("INSERT INTO attempts VALUES (?, ?, ?)", (kind, subject, now))
            return blocked

    def session(self, request: Request):
        token = request.cookies.get(COOKIE, "")
        if len(token) != 64:
            return None
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            return db.execute("SELECT * FROM sessions WHERE token_hash=?", (digest(token),)).fetchone()

    async def admin_form(self, request: Request) -> tuple[dict, sqlite3.Row]:
        session = self.session(request)
        if session is None:
            raise HTTPException(401, "Administrator login required")
        fields = await self.form(request)
        if not hmac.compare_digest(fields.get("csrf", ""), session["csrf"]):
            raise HTTPException(403, "CSRF validation failed")
        return fields, session

    async def enroll(self, request: Request):
        if self.throttle(request, "enroll", 30, 3600, 3000):
            raise HTTPException(429, "Enrollment rate exceeded")
        data = await self.json_body(request, {"client_version", "platform"})
        if not valid_version(data["client_version"]) or data["platform"] not in ("windows", "macos"):
            raise HTTPException(400, "Invalid version or platform")
        installation_id, token = str(uuid.uuid4()), secrets.token_hex(32)
        now = int(time.time())
        with self.db() as db:
            db.execute("INSERT INTO installations(id, token_hash, version, platform, created_at, last_seen) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (installation_id, digest(token), data["client_version"], data["platform"], now, now))
        return JSONResponse({"installation_id": installation_id, "installation_token": token}, status_code=201)

    async def authorize(self, request: Request):
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not re.fullmatch(r"[0-9a-f]{64}", authorization[7:]):
            raise HTTPException(401, "Invalid installation credentials")
        data = await self.json_body(request, {"installation_id", "version", "command", "nonce"})
        try:
            valid_id = str(uuid.UUID(data["installation_id"])) == data["installation_id"]
        except ValueError:
            valid_id = False
        if (not valid_id or not valid_version(data["version"]) or not COMMAND.fullmatch(data["command"])
                or not NONCE.fullmatch(data["nonce"])):
            raise HTTPException(400, "Invalid authorization fields")
        now = int(time.time())
        with self.db() as db:
            installation = db.execute("SELECT * FROM installations WHERE id=?", (data["installation_id"],)).fetchone()
            if installation is None or not hmac.compare_digest(installation["token_hash"], digest(authorization[7:])):
                raise HTTPException(401, "Invalid installation credentials")
            policy = db.execute("SELECT * FROM policy WHERE id=1").fetchone()
            version = db.execute("SELECT * FROM versions WHERE version=?", (data["version"],)).fetchone()
            code, reason = "allowed", ""
            if policy["paused"]:
                code, reason = "maintenance", policy["reason"]
            elif installation["paused"]:
                code, reason = "installation_paused", installation["reason"]
            elif version is not None and version["paused"]:
                code, reason = "version_paused", version["reason"]
            elif policy["minimum_version"] and tuple(map(int, data["version"].split("."))) < tuple(map(int, policy["minimum_version"].split("."))):
                code, reason = "update_required", "필수 업데이트: 최소 지원 버전 " + policy["minimum_version"]
            db.execute("UPDATE installations SET last_seen=?, version=? WHERE id=?",
                       (now, data["version"], data["installation_id"]))
        payload = {"protocol": 1, "installation_id": data["installation_id"], "version": data["version"],
                   "command": data["command"], "nonce": data["nonce"], "allowed": code == "allowed",
                   "code": code, "reason": reason, "issued_at": now, "expires_at": now + 30}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        signature = self.key.sign(encoded, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        return JSONResponse({"payload": base64.b64encode(encoded).decode("ascii"),
                             "signature": base64.b64encode(signature).decode("ascii")})

    async def login_page(self, request: Request):
        csrf = secrets.token_hex(32)
        response = page("관리자 로그인", f'''<p>관리자는 MCP 요청의 허용 여부만 관리합니다. Rhino 모델은 전송되지 않습니다.</p>
            <form method="post" action="/admin/login"><input type="hidden" name="csrf" value="{csrf}">
            <label>관리자 비밀번호<input name="password" type="password" minlength="14" maxlength="1024" required autocomplete="current-password"></label>
            <button>로그인</button></form>''')
        response.set_cookie("rhino_login_csrf", csrf, max_age=600, secure=not self.insecure,
                            httponly=True, samesite="strict", path="/admin/login")
        return response

    async def login(self, request: Request):
        if self.throttle(request, "login", 5, 900, 30):
            raise HTTPException(429, "로그인 시도가 너무 많습니다. 15분 후 다시 시도해 주세요.")
        fields = await self.form(request)
        csrf = request.cookies.get("rhino_login_csrf", "")
        if len(csrf) != 64 or not hmac.compare_digest(csrf, fields.get("csrf", "")):
            raise HTTPException(403, "CSRF validation failed")
        password = fields.get("password", "")
        if not 14 <= len(password) <= 1024:
            raise HTTPException(401, "비밀번호를 확인해 주세요.")
        with self.db() as db:
            admin = db.execute("SELECT * FROM admin WHERE id=1").fetchone()
            if not hmac.compare_digest(password_hash(password, bytes.fromhex(admin["salt"])), admin["hash"]):
                self.audit(db, "login_failed")
                # Commit before raising so the audit entry is retained.
                db.commit()
                raise HTTPException(401, "비밀번호를 확인해 주세요.")
            token, csrf = secrets.token_hex(32), secrets.token_hex(32)
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (digest(token), csrf, int(time.time()) + SESSION_SECONDS))
            self.audit(db, "login")
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, secure=not self.insecure,
                            httponly=True, samesite="strict", path="/admin")
        response.delete_cookie("rhino_login_csrf", path="/admin/login", secure=not self.insecure,
                               httponly=True, samesite="strict")
        return response

    async def logout(self, request: Request):
        _, session = await self.admin_form(request)
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (session["token_hash"],))
            self.audit(db, "logout")
        response = RedirectResponse("/admin/login", status_code=303)
        response.delete_cookie(COOKIE, path="/admin", secure=not self.insecure, httponly=True, samesite="strict")
        return response

    async def dashboard(self, request: Request):
        session = self.session(request)
        if session is None:
            return RedirectResponse("/admin/login", status_code=303)
        with self.db() as db:
            policy = db.execute("SELECT * FROM policy WHERE id=1").fetchone()
            versions = db.execute("SELECT * FROM versions ORDER BY version").fetchall()
            installations = db.execute("SELECT id, version, platform, created_at, last_seen, paused, reason "
                                       "FROM installations ORDER BY last_seen DESC LIMIT 100").fetchall()
            audits = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100").fetchall()
        csrf = f'<input type="hidden" name="csrf" value="{session["csrf"]}">'
        state = "일시 중지" if policy["paused"] else "정상 운영"
        content = f'''<div class="status">현재 정책: <strong>{state}</strong></div>
        <p>정책 저장 후 다음 온라인 승인 요청부터 적용됩니다. 진행 중인 Rhino 작업은 강제 종료하지 않습니다.</p>
        <section><h2>전체 운영 정책</h2><form method="post" action="/admin/policy">{csrf}
        <label>운영 상태<select name="paused"><option value="0" {selected(not policy['paused'])}>정상 운영</option>
        <option value="1" {selected(policy['paused'])}>새 MCP 요청 일시 중지</option></select></label>
        <label>중지 안내<input name="reason" maxlength="500" value="{esc(policy['reason'])}" placeholder="중지 시 사유를 입력하세요"></label>
        <label>최소 지원 버전<input name="minimum_version" value="{esc(policy['minimum_version'])}" placeholder="예: 0.6.0 / 제한 없음: 빈칸"></label>
        <button>전체 정책 저장</button></form></section>
        <section><h2>버전별 정책</h2><form method="post" action="/admin/version">{csrf}
        <label>정확한 버전<input name="version" required placeholder="0.6.0"></label>
        <label>상태<select name="paused"><option value="1">일시 중지</option><option value="0">재개</option></select></label>
        <label>안내<input name="reason" maxlength="500"></label><button>버전 정책 저장</button></form>
        <table><thead><tr><th>버전</th><th>상태</th><th>안내</th></tr></thead><tbody>'''
        content += "".join(f"<tr><td>{esc(v['version'])}</td><td>{'중지' if v['paused'] else '정상'}</td><td>{esc(v['reason'])}</td></tr>" for v in versions)
        content += '''</tbody></table></section><section><h2>설치 목록 · 최근 접속 100개</h2>
        <p>개별 중지는 해당 설치 등록에 적용됩니다. 로그인 없는 공개 등록이므로 재설치로 새 등록을 만들 수 있습니다. 전체·버전 정책은 새 등록에도 적용됩니다.</p>
        <table><thead><tr><th>설치 ID / 환경</th><th>최근 승인 확인 (UTC)</th><th>상태</th><th>변경</th></tr></thead><tbody>'''
        for item in installations:
            content += f'''<tr><td><code>{esc(item['id'])}</code><br>{esc(item['platform'])} · {esc(item['version'])}</td>
            <td>{utc(item['last_seen'])}</td><td>{'중지' if item['paused'] else '정상'}<br>{esc(item['reason'])}</td>
            <td><form method="post" action="/admin/installation">{csrf}<input type="hidden" name="installation_id" value="{esc(item['id'])}">
            <input type="hidden" name="paused" value="{0 if item['paused'] else 1}">
            <label>안내<input name="reason" maxlength="500" aria-label="설치 중지 안내"></label>
            <button>{'재개' if item['paused'] else '중지'}</button></form></td></tr>'''
        content += '</tbody></table></section><section><h2>관리 기록 · 최근 100개</h2><table><thead><tr><th>UTC</th><th>작업</th><th>대상</th><th>내용</th></tr></thead><tbody>'
        content += "".join(f"<tr><td>{utc(a['at'])}</td><td>{esc(a['action'])}</td><td>{esc(a['target'])}</td><td>{esc(a['detail'])}</td></tr>" for a in audits)
        content += f'</tbody></table></section><form method="post" action="/admin/logout">{csrf}<button>로그아웃</button></form>'
        return page("RhinoMCP 운영 관리", content)

    async def update_policy(self, request: Request):
        fields, _ = await self.admin_form(request)
        paused, reason = parse_policy(fields)
        minimum = fields.get("minimum_version", "").strip()
        if minimum and not valid_version(minimum):
            raise HTTPException(400, "최소 버전은 0.6.0 형식으로 입력하세요.")
        with self.db() as db:
            db.execute("UPDATE policy SET paused=?, reason=?, minimum_version=? WHERE id=1", (paused, reason, minimum))
            self.audit(db, "global_policy", "all", json.dumps({"paused": bool(paused), "reason": reason, "minimum_version": minimum}, ensure_ascii=False))
        return RedirectResponse("/admin", status_code=303)

    async def update_version(self, request: Request):
        fields, _ = await self.admin_form(request)
        paused, reason = parse_policy(fields)
        version = fields.get("version", "").strip()
        if not valid_version(version):
            raise HTTPException(400, "버전은 0.6.0 형식으로 입력하세요.")
        with self.db() as db:
            db.execute("INSERT INTO versions VALUES (?, ?, ?) ON CONFLICT(version) DO UPDATE SET paused=excluded.paused, reason=excluded.reason", (version, paused, reason))
            self.audit(db, "version_pause" if paused else "version_resume", version, reason)
        return RedirectResponse("/admin", status_code=303)

    async def update_installation(self, request: Request):
        fields, _ = await self.admin_form(request)
        paused, reason = parse_policy(fields)
        target = fields.get("installation_id", "")
        with self.db() as db:
            result = db.execute("UPDATE installations SET paused=?, reason=? WHERE id=?", (paused, reason, target))
            if result.rowcount != 1:
                raise HTTPException(404, "설치 정보를 찾을 수 없습니다.")
            self.audit(db, "installation_pause" if paused else "installation_resume", target, reason)
        return RedirectResponse("/admin", status_code=303)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def utc(value: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(value))


def selected(condition) -> str:
    return "selected" if condition else ""


def parse_policy(fields: dict) -> tuple[int, str]:
    if fields.get("paused") not in ("0", "1"):
        raise HTTPException(400, "운영 상태가 올바르지 않습니다.")
    reason = fields.get("reason", "").strip()
    if len(reason) > 500 or (fields["paused"] == "1" and not reason):
        raise HTTPException(400, "중지 안내를 1~500자로 입력하세요.")
    return int(fields["paused"]), reason


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
    <link rel="stylesheet" href="/admin/style.css"></head><body><main><h1>{esc(title)}</h1>{body}</main></body></html>''')


CSS = """*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#202b3b;font:15px/1.65 system-ui,sans-serif}main{max-width:1120px;margin:40px auto;padding:0 22px 50px}h1{font-size:28px}h2{font-size:20px;margin-top:0}section{background:white;border:1px solid #dce2e9;border-radius:12px;padding:22px;margin:24px 0}label{display:block;margin:12px 0}input,select,button{font:inherit;border:1px solid #bac6d3;border-radius:6px;padding:9px 12px}input,select{display:block;width:100%;max-width:620px;background:#fff}button{background:#194985;color:white;cursor:pointer;margin:8px 0}button:hover{background:#123965}input:focus,select:focus,button:focus{outline:3px solid #83b6ed;outline-offset:2px}.status{background:#e1ebf8;padding:16px;border-radius:8px}table{width:100%;border-collapse:collapse;font-size:13px;display:block;overflow:auto}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #e1e6ec}td{overflow-wrap:anywhere}code{font-size:12px}p{max-width:900px}td form input{min-width:160px}@media(max-width:600px){main{margin:20px auto;padding:0 12px}section{padding:15px}}"""


def create_app(state: Path, insecure_loopback: bool = False, public_url: str | None = None) -> Starlette:
    service = Service(state, insecure_loopback)
    if public_url is None:
        raise ValueError("A canonical public_url is required, including for local development")
    origin = validate_url(public_url, insecure_loopback)
    expected_host = urlsplit(origin).netloc.lower()

    async def health(request):
        # Deliberately no policy, credentials, installation details, or paths.
        return JSONResponse({"status": "ok", "protocol": 1})

    async def public_profile(request):
        # Pinning material for the owner's release build; never exports private state.
        return JSONResponse(service.profile(origin, insecure_loopback))

    async def style(request):
        return Response(CSS, media_type="text/css")

    async def error(request, exc):
        message = str(exc.detail) if isinstance(exc, HTTPException) else "Internal service error"
        status = exc.status_code if isinstance(exc, HTTPException) else 500
        if request.url.path.startswith("/admin"):
            return HTMLResponse(
                f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>요청 오류</title><p>{esc(message)}</p><a href="/admin">관리 화면으로</a></html>', status_code=status)
        return JSONResponse({"error": message}, status_code=status)

    app = Starlette(routes=[
        Route("/healthz", health), Route("/v1/profile", public_profile),
        Route("/v1/enroll", service.enroll, methods=["POST"]),
        Route("/v1/authorize", service.authorize, methods=["POST"]),
        Route("/admin", service.dashboard), Route("/admin/style.css", style),
        Route("/admin/login", service.login_page, methods=["GET"]),
        Route("/admin/login", service.login, methods=["POST"]),
        Route("/admin/logout", service.logout, methods=["POST"]),
        Route("/admin/policy", service.update_policy, methods=["POST"]),
        Route("/admin/version", service.update_version, methods=["POST"]),
        Route("/admin/installation", service.update_installation, methods=["POST"]),
    ], exception_handlers={HTTPException: error})
    app.state.service = service

    async def headers(request: Request, call_next):
        # Development bypass is bound to loopback even if an embedding host misconfigures its socket.
        if service.insecure and (not request.client or request.client.host not in ("127.0.0.1", "::1", "testclient")):
            return JSONResponse({"error": "Development service is loopback-only"}, status_code=403)
        if request.headers.get("host", "").lower() != expected_host:
            return JSONResponse({"error": "Unrecognized service host"}, status_code=400)
        if request.headers.get("origin") and request.headers["origin"] != origin:
            return JSONResponse({"error": "Unrecognized request origin"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        if not service.insecure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=headers)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="Private persistent state directory")
    commands = parser.add_subparsers(dest="action", required=True)
    init = commands.add_parser("init", help="Create signing key and administrator password hash")
    init.add_argument("--password-file", type=Path, help="Read password from owner-only file; otherwise prompt")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--public-url", help="Canonical HTTPS origin in production; generated from loopback host/port in development")
    serve.add_argument("--trust-proxy-headers", action="store_true", help="Production private backend only: trust the exclusive reverse proxy's client IP headers")
    serve.add_argument("--allow-insecure-loopback", action="store_true", help="Development only: HTTP and non-Secure local cookie")
    export = commands.add_parser("export-profile")
    export.add_argument("--url", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--allow-insecure-loopback", action="store_true")
    reset = commands.add_parser("reset-password", help="Owner recovery; invalidates all admin sessions")
    reset.add_argument("--password-file", type=Path)
    args = parser.parse_args()
    try:
        if args.action in ("init", "reset-password"):
            password = args.password_file.read_text(encoding="utf-8").rstrip("\r\n") if args.password_file else getpass.getpass("New administrator password (14+ characters): ")
            if not 14 <= len(password) <= 1024:
                raise ValueError("Administrator password must contain 14 to 1024 characters")
            if not args.password_file and password != getpass.getpass("Confirm password: "):
                raise ValueError("Passwords do not match")
            if args.action == "init":
                initialize(args.state, password)
            else:
                service = Service(args.state)
                salt = secrets.token_bytes(32)
                with service.db() as db:
                    db.execute("UPDATE admin SET salt=?, hash=? WHERE id=1", (salt.hex(), password_hash(password, salt)))
                    db.execute("DELETE FROM sessions")
                    service.audit(db, "password_reset", "administrator")
            print("Administrator state initialized." if args.action == "init" else "Password changed; previous administrator sessions revoked.")
        elif args.action == "export-profile":
            service = Service(args.state)
            profile = service.profile(args.url, args.allow_insecure_loopback)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as file:
                json.dump(profile, file, indent=2)
                file.write("\n")
            print("Public client profile exported. It contains no private key or administrator credential.")
        else:
            if args.allow_insecure_loopback and args.host not in ("127.0.0.1", "::1", "localhost"):
                raise ValueError("Insecure development server must bind to an exact loopback host")
            if args.allow_insecure_loopback and args.trust_proxy_headers:
                raise ValueError("Development loopback mode cannot trust proxy headers")
            if not 1 <= args.port <= 65535:
                raise ValueError("Port must be between 1 and 65535")
            import uvicorn
            public_url = args.public_url
            if public_url is None and args.allow_insecure_loopback:
                host = "[::1]" if args.host == "::1" else args.host
                public_url = f"http://{host}:{args.port}"
            uvicorn.run(create_app(args.state, args.allow_insecure_loopback, public_url), host=args.host,
                        port=args.port, access_log=False, proxy_headers=args.trust_proxy_headers,
                        forwarded_allow_ips="*" if args.trust_proxy_headers else "", server_header=False,
                        limit_concurrency=100)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
