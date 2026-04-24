/**
 * node/index.js
 *
 * - /api に来たリクエストを Japan Post Digital Address API へプロキシする
 * - それ以外は shared/frontend/index.html を返す（画面表示）
 *
 * 前提となるファイル／ディレクトリ：
 * - shared/frontend/index.html
 * - shared/config/credentials.json（ユーザーが配置）
 * - shared/runtime/access_token.json（自動生成）
 */

const express = require("express");
const fs = require("fs");
const path = require("path");

const ROOT_DIR = path.join(__dirname, "..");
const SHARED_DIR = path.join(ROOT_DIR, "shared");
const FRONTEND_DIR = path.join(SHARED_DIR, "frontend");
const FRONTEND_HTML = path.join(FRONTEND_DIR, "index.html");
const CONFIG_DIR = path.join(SHARED_DIR, "config");
const RUNTIME_DIR = path.join(SHARED_DIR, "runtime");
const CREDENTIALS_FILE = path.join(CONFIG_DIR, "credentials.json");
const TOKEN_FILE = path.join(RUNTIME_DIR, "access_token.json");

const BIND_HOST = process.env.BIND_HOST ?? process.env.HOST ?? "127.0.0.1";
const PORT = Number(process.env.PORT ?? 8000);
const PUBLIC_HOST =
  process.env.PUBLIC_HOST ?? (BIND_HOST === "0.0.0.0" ? "127.0.0.1" : BIND_HOST);
const PUBLIC_PORT = Number(process.env.PUBLIC_PORT ?? PORT);
const LISTEN_URL = `http://${BIND_HOST}:${PORT}`;
const ACCESS_URL = `http://${PUBLIC_HOST}:${PUBLIC_PORT}`;

const app = express();

/* ========= ミドルウェア ========= */

app.use(express.static(FRONTEND_DIR));

app.use((req, res, next) => {
  const pathWithQuery = req.originalUrl || req.url || "/";
  res.on("finish", () => {
    const normalized = pathWithQuery.startsWith("/")
      ? pathWithQuery
      : `/${pathWithQuery}`;
    console.log(
      `[node-proxy] ${req.method} ${ACCESS_URL}${normalized} -> ${res.statusCode}`,
    );
  });
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  if (req.method !== "GET") {
    res.status(204).end();
    return;
  }
  next();
});

/* ========= ルーティング ========= */

app.get("/api", handleApiRequest);
app.get("/api/*", handleApiRequest);
app.get("*", serveIndexHtml);

app.listen(PORT, BIND_HOST, () => {
  console.log(`[node-proxy] Listening inside container on ${LISTEN_URL}`);
  console.log(`[node-proxy] Access from host via ${ACCESS_URL}/`);
  console.log(
    `[node-proxy] Quick check: ${ACCESS_URL}/api?search_code=1000001`,
  );
});

/* ========= 画面返却 ========= */

function serveIndexHtml(_req, res) {
  res.sendFile(FRONTEND_HTML);
}

/* ========= API処理 ========= */

async function handleApiRequest(req, res) {
  res.type("application/json");

  const searchCode = getSearchCode(req);

  try {
    const credsResult = loadCredentials();
    if (!credsResult.ok) {
      res
        .status(credsResult.status)
        .type("application/json")
        .send(credsResult.body);
      return;
    }
    const credentials = credsResult.data;
    const hostname = credentials.hostname;

    const tokenResult = await getAccessTokenOrFetch(credentials);
    if (!tokenResult.ok) {
      res
        .status(tokenResult.status)
        .type("application/json")
        .send(tokenResult.body);
      return;
    }

    await proxyJapanPostApi(res, tokenResult.token, hostname, searchCode);
  } catch (error) {
    res.status(500).json({ error: "internal_error", message: String(error) });
  }
}

function loadCredentials() {
  if (!fs.existsSync(CREDENTIALS_FILE)) {
    return {
      ok: false,
      status: 500,
      body: JSON.stringify({ error: "credentials.json not found" })
    };
  }

  let data;
  try {
    data = JSON.parse(fs.readFileSync(CREDENTIALS_FILE, "utf8"));
  } catch (error) {
    return {
      ok: false,
      status: 500,
      body: JSON.stringify({
        error: "invalid_credentials",
        message: "credentials.json is not valid JSON"
      })
    };
  }

  if (typeof data.hostname !== "string" || data.hostname === "") {
    return {
      ok: false,
      status: 500,
      body: JSON.stringify({
        error: "invalid_credentials",
        message: "hostname is required in credentials.json"
      })
    };
  }

  return { ok: true, data };
}

function getSearchCode(req) {
  if (typeof req.query.search_code === "string") {
    return req.query.search_code;
  }

  const remainder = typeof req.params?.[0] === "string" ? req.params[0] : "";
  return remainder.length > 0 ? decodeURIComponent(remainder.replace(/^\/?/, "")) : "";
}

async function getAccessTokenOrFetch(credentials) {
  const hostname = credentials.hostname;

  const cached = loadCachedToken(hostname);
  if (cached !== null) {
    return { ok: true, token: cached };
  }

  const fetched = await fetchNewToken(credentials);
  if (!fetched.ok) {
    return fetched;
  }

  let parsed;
  try {
    parsed = JSON.parse(fetched.body);
  } catch (error) {
    return {
      ok: false,
      status: 500,
      body: JSON.stringify({ error: "invalid_token_response", message: String(error) })
    };
  }
  if (typeof parsed.token !== "string") {
    return {
      ok: false,
      status: 500,
      body: JSON.stringify({ error: "invalid_token_response", message: "token missing" })
    };
  }

  ensureRuntimeDir();
  const toStore = { ...parsed, hostname };
  fs.writeFileSync(TOKEN_FILE, JSON.stringify(toStore), "utf8");

  return { ok: true, token: parsed.token };
}

function loadCachedToken(hostname) {
  if (!fs.existsSync(TOKEN_FILE)) {
    return null;
  }

  try {
    const data = JSON.parse(fs.readFileSync(TOKEN_FILE, "utf8"));
    if (
      typeof data.token !== "string" ||
      typeof data.expires_in !== "number" ||
      !Number.isFinite(data.expires_in)
    ) {
      return null;
    }
    if (data.hostname !== hostname) {
      return null;
    }

    const expiresAt =
      Math.floor(fs.statSync(TOKEN_FILE).mtimeMs / 1000) + data.expires_in;
    if (Math.floor(Date.now() / 1000) < expiresAt) {
      return data.token;
    }
  } catch {
    return null;
  }

  return null;
}

async function fetchNewToken(credentials) {
  const payload = {
    grant_type: credentials.grant_type ?? "client_credentials",
    client_id: credentials.client_id ?? "",
    secret_key: credentials.secret_key ?? ""
  };

  const response = await fetch(`https://${credentials.hostname}/api/v2/j/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-forwarded-for": "127.0.0.1"
    },
    body: JSON.stringify(payload)
  });

  const body = await response.text();
  if (!response.ok) {
    return { ok: false, status: response.status, body };
  }

  return { ok: true, status: response.status, body };
}

async function proxyJapanPostApi(res, token, hostname, searchCode) {
  if (isZipOrCode(searchCode)) {
    const apiResp = await fetch(
      `https://${hostname}/api/v2/searchcode/${encodeURIComponent(searchCode)}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const body = await apiResp.text();
    res.status(apiResp.status).type("application/json").send(body);
    return;
  }

  const apiResp = await fetch(`https://${hostname}/api/v2/addresszip`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ freeword: searchCode })
  });
  const body = await apiResp.text();
  res.status(apiResp.status).type("application/json").send(body);
}

function isZipOrCode(value) {
  return /^\d{3,7}$/.test(value) || /^\w{7}$/.test(value);
}

function ensureRuntimeDir() {
  fs.mkdirSync(RUNTIME_DIR, { recursive: true });
}

