import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import unquote

import requests
from flask import Flask, Response, request, send_file

# =========================
#  python/index.py
# -------------------------
# - /api に来たリクエストを Japan Post Digital Address API へプロキシする
# - それ以外は shared/frontend/index.html を返す（画面表示）
#
# 必要なファイル／ディレクトリ：
# - shared/frontend/index.html
# - shared/config/credentials.json（ユーザーが配置）
# - shared/runtime/access_token.json（自動生成）
# =========================

ROOT_DIR = Path(__file__).resolve().parent.parent
SHARED_DIR = ROOT_DIR / "shared"
FRONTEND_DIR = SHARED_DIR / "frontend"
FRONTEND_HTML = FRONTEND_DIR / "index.html"
CONFIG_DIR = SHARED_DIR / "config"
RUNTIME_DIR = SHARED_DIR / "runtime"
TOKEN_FILE = RUNTIME_DIR / "access_token.json"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"

BIND_HOST = os.environ.get("BIND_HOST") or os.environ.get("HOST", "127.0.0.1")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST") or "127.0.0.1"
PORT = int(os.environ.get("PORT", "8003"))
PUBLIC_PORT = int(os.environ.get("PUBLIC_PORT", PORT))
LISTEN_URL = f"http://{BIND_HOST}:{PORT}"
ACCESS_URL = f"http://{PUBLIC_HOST}:{PUBLIC_PORT}"

app = Flask(__name__)

# Ensure application logs flush immediately when running under docker compose
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
else:
    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)

werkzeug_logger = logging.getLogger("werkzeug")
werkzeug_logger.setLevel(logging.WARNING)
for handler in list(werkzeug_logger.handlers):
    handler.setLevel(logging.WARNING)
werkzeug_logger.propagate = False

app.logger.handlers.clear()
app.logger.setLevel(logging.WARNING)
app.logger.propagate = False


# ========= ミドルウェア =========

@app.after_request
def addCorsHeaders(response: Response) -> Response:
    if request.path.startswith("/api"):
        origin = request.headers.get("Origin")
        response.headers["Access-Control-Allow-Origin"] = origin or "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    full_path = request.full_path if request.query_string else request.path
    if full_path.endswith("?"):
        full_path = full_path[:-1]
    print(
        f"[python-proxy] {request.method} {ACCESS_URL}{full_path or '/'} -> {response.status_code}",
    )
    return response


@app.before_request
def enforceGetForApi() -> Optional[Response]:
    if request.path.startswith("/api") and request.method != "GET":
        return Response(status=204)
    return None


# ========= ルーティング =========

@app.route("/api", defaults={"fallback": ""})
@app.route("/api/<path:fallback>")
def apiRoute(fallback: str) -> Response:
    return handleApiRequest(fallback)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def indexRoute(path: str) -> Response:  # type: ignore[unused-argument]
    return serveIndexHtml()


# ========= ハンドラー =========

def serveIndexHtml() -> Response:
    if FRONTEND_HTML.exists():
        return send_file(FRONTEND_HTML)
    return Response(
        "shared/frontend/index.html not found",
        status=404,
        mimetype="text/plain",
    )


def handleApiRequest(fallback: str) -> Response:
    search_code = getSearchCode(fallback)

    creds_result = loadCredentials()
    if not creds_result["ok"]:
        return Response(
            creds_result["body"],
            status=creds_result["status"],
            mimetype="application/json",
        )
    credentials = creds_result["data"]
    hostname = credentials["hostname"]

    token_result = getAccessTokenOrFetch(credentials)
    if not token_result["ok"]:
        return Response(
            token_result["body"],
            status=token_result["status"],
            mimetype="application/json",
        )

    return proxyJapanPostApi(token_result["token"], hostname, search_code)


def loadCredentials() -> Dict[str, object]:
    if not CREDENTIALS_FILE.exists():
        return {
            "ok": False,
            "status": 500,
            "body": json.dumps({"error": "credentials.json not found"}),
        }

    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {
            "ok": False,
            "status": 500,
            "body": json.dumps(
                {"error": "invalid_credentials", "message": "credentials.json is not valid JSON"},
                ensure_ascii=False,
            ),
        }

    hostname = data.get("hostname")
    if not isinstance(hostname, str) or not hostname:
        return {
            "ok": False,
            "status": 500,
            "body": json.dumps(
                {"error": "invalid_credentials", "message": "hostname is required in credentials.json"},
                ensure_ascii=False,
            ),
        }

    return {"ok": True, "data": data}


def getSearchCode(fallback: str) -> str:
    if "search_code" in request.args:
        return str(request.args.get("search_code", ""))
    return unquote(fallback) if fallback else ""


def getAccessTokenOrFetch(credentials: Dict[str, object]) -> Dict[str, object]:
    hostname = str(credentials["hostname"])

    cached = loadCachedToken(hostname)
    if cached:
        return {"ok": True, "token": cached}

    fetched = fetchNewToken(credentials)
    if not fetched["ok"]:
        return fetched

    try:
        data = json.loads(fetched["body"])
        token = data["token"]
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": 500,
            "body": json.dumps(
                {"error": "invalid_token_response", "message": str(exc)},
                ensure_ascii=False,
            ),
        }

    ensureRuntimeDir()
    # 応答に hostname を併記して保存（hostname 切替時の自動無効化用）
    TOKEN_FILE.write_text(
        json.dumps({**data, "hostname": hostname}, ensure_ascii=False),
        encoding="utf-8",
    )

    return {"ok": True, "token": token}


def loadCachedToken(hostname: str) -> Optional[str]:
    if not TOKEN_FILE.exists():
        return None

    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        if data.get("hostname") != hostname:
            return None

        expires_in = int(data["expires_in"])
        token = str(data["token"])

        expires_at = int(TOKEN_FILE.stat().st_mtime) + expires_in
        if int(time.time()) < expires_at:
            return token
    except Exception:  # noqa: BLE001
        return None

    return None


def fetchNewToken(credentials: Dict[str, object]) -> Dict[str, object]:
    hostname = credentials["hostname"]
    payload = {
        "grant_type": credentials.get("grant_type", "client_credentials"),
        "client_id": credentials.get("client_id", ""),
        "secret_key": credentials.get("secret_key", ""),
    }

    response = requests.post(
        f"https://{hostname}/api/v2/j/token",
        headers={
            "Content-Type": "application/json",
            "x-forwarded-for": "127.0.0.1",
        },
        json=payload,
        timeout=30,
    )

    return {
        "ok": response.status_code == 200,
        "status": response.status_code,
        "body": response.text or "",
    }


def proxyJapanPostApi(token: str, hostname: str, search_code: str) -> Response:
    if isZipOrCode(search_code):
        response = requests.get(
            f"https://{hostname}/api/v2/searchcode/{requests.utils.quote(search_code)}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    else:
        response = requests.post(
            f"https://{hostname}/api/v2/addresszip",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"freeword": search_code},
            timeout=30,
        )

    return Response(
        response.text,
        status=response.status_code,
        mimetype="application/json",
    )


def isZipOrCode(value: str) -> bool:
    return bool(re.match(r"^\d{3,7}$", value) or re.match(r"^\w{7}$", value))


def ensureRuntimeDir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    print(f"[python-proxy] Listening inside container on {LISTEN_URL}")
    print(f"[python-proxy] Access from host via {ACCESS_URL}/")
    print(f"[python-proxy] Quick check: {ACCESS_URL}/api?search_code=1000001")
    app.run(host=BIND_HOST, port=PORT, debug=False)
