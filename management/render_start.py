"""Start the single-node management service on Render's persistent disk."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from typing import Mapping, MutableMapping

from control_service import create_app, initialize, validate_url


@dataclass(frozen=True)
class Configuration:
    state: Path
    public_url: str
    port: int


def configuration(environment: Mapping[str, str]) -> Configuration:
    public_url = validate_url(
        environment.get("RHINOMCP_PUBLIC_URL") or environment.get("RENDER_EXTERNAL_URL", ""), False)
    port_text = environment.get("PORT", "10000")
    if not port_text.isascii() or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    state = Path(environment.get("RHINOMCP_STATE_DIR", "/var/data/rhinomcp"))
    if not state.is_absolute():
        raise ValueError("RHINOMCP_STATE_DIR must be an absolute persistent directory")
    return Configuration(state, public_url, int(port_text))


def prepare_app(environment: MutableMapping[str, str]):
    config = configuration(environment)
    # Remove the bootstrap secret from this process's environment. The operator
    # separately removes it from Render's dashboard after the first deployment.
    password = environment.pop("RHINOMCP_BOOTSTRAP_PASSWORD", "")
    state = config.state
    if not state.exists() or (state.is_dir() and not any(state.iterdir())):
        if not password:
            raise ValueError("Empty state requires RHINOMCP_BOOTSTRAP_PASSWORD for first initialization")
        initialize(state, password)
    elif not ((state / "signing-key.pem").is_file() and (state / "control.sqlite3").is_file()):
        raise ValueError("Incomplete persistent state; restore the original key and database together")
    del password

    # Existing state must be complete. Never create missing tables or reset it to
    # make startup succeed: doing that would invalidate installed clients.
    database_url = (state / "control.sqlite3").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(database_url, uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"admin", "policy", "versions", "installations", "sessions", "attempts", "audit"}
        if (not required.issubset(tables)
                or db.execute("PRAGMA quick_check").fetchone() != ("ok",)
                or db.execute("SELECT count(*) FROM admin WHERE id=1").fetchone() != (1,)
                or db.execute("SELECT count(*) FROM policy WHERE id=1").fetchone() != (1,)):
            raise ValueError("Invalid persistent database; restore the original state backup")
    return create_app(state, public_url=config.public_url), config


def main() -> None:
    import uvicorn

    app, config = prepare_app(os.environ)
    uvicorn.run(app, host="0.0.0.0", port=config.port, workers=1, access_log=False,
                proxy_headers=False, server_header=False, limit_concurrency=100)


if __name__ == "__main__":
    main()
