<?php
/**
 * index.php
 *
 * - /api で呼ばれたとき：Japan Post Digital Address API のプロキシ（JSON返却）
 * - それ以外：index.html を返す（画面表示）
 *
 * 同階層に以下がある前提：
 * - index.html
 * - credentials.json
 * - access_token.json（自動生成）
 */

/* ========= ルーティング（/api 判定） ========= */
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

if ($path === '/api') {
    handle_api_request();
    exit;
}

// /api 以外は index.html を返す
serve_index_html();
exit;


/* ========= 画面返却 ========= */
function serve_index_html(): void
{
    header('Content-Type: text/html; charset=utf-8');

    $html = __DIR__ . '/index.html';
    if (file_exists($html)) {
        readfile($html);
        return;
    }

    http_response_code(404);
    echo "index.html not found";
}


/* ========= API処理 ========= */
function handle_api_request(): void
{
    // CORS（API用）
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: *');
    header('Access-Control-Allow-Headers: *');

    // GET以外は 204（元処理と同等）
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
        http_response_code(204);
        exit;
    }

    // search_code の取得（元処理を踏襲）
    $search_code = get_search_code();

    // Token確保（キャッシュ→なければ取得）
    $token = get_access_token_or_fetch();

    // Japan Post APIへリクエストして、そのまま返却
    proxy_japanpost_api($token, $search_code);
}


/* ========= search_code 取得 ========= */
function get_search_code(): string
{
    // クエリ優先
    if (isset($_GET['search_code'])) {
        return (string)$_GET['search_code'];
    }

    // クエリが無い場合はパスの末尾（元処理踏襲）
    $path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $fallback = rawurldecode(ltrim($path ?? '', '/'));
    return (string)$fallback;
}


/* ========= アクセストークン取得 ========= */
function get_access_token_or_fetch(): string
{
    $token_filename = __DIR__ . '/access_token.json';

    // キャッシュがあれば利用
    $cached = load_cached_token($token_filename);
    if ($cached !== null) {
        return $cached;
    }

    // 無ければ取得
    $result = fetch_new_token();
    if ($result['status'] !== 200) {
        http_response_code($result['status']);
        header('Content-Type: application/json');
        echo $result['body'];
        exit;
    }

    // 保存して返す
    file_put_contents($token_filename, $result['body']);
    $obj = json_decode($result['body']);
    return $obj->token;
}


/* ========= トークンキャッシュ読み込み ========= */
function load_cached_token(string $token_filename): ?string
{
    if (!file_exists($token_filename)) {
        return null;
    }

    $json = file_get_contents($token_filename);
    if ($json === false) {
        return null;
    }

    $obj = json_decode($json);
    if (!$obj || !isset($obj->expires_in, $obj->token)) {
        return null;
    }

    // PHP元処理： time() < filemtime + expires_in
    $expiresAt = filemtime($token_filename) + (int)$obj->expires_in;
    if (time() < $expiresAt) {
        return (string)$obj->token;
    }

    return null;
}


/* ========= 新規トークン取得 ========= */
function fetch_new_token(): array
{
    $credentials_file = __DIR__ . '/credentials.json';
    if (!file_exists($credentials_file)) {
        return [
            'status' => 500,
            'body'   => json_encode(['error' => 'credentials.json not found'], JSON_UNESCAPED_UNICODE),
        ];
    }

    $ch = curl_init('https://api.da.pf.japanpost.jp/api/v1/j/token');
    curl_setopt($ch, CURLOPT_USERAGENT, 'curl/' . curl_version()['version']);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json',
        'x-forwarded-for: 127.0.0.1',
    ]);
    curl_setopt($ch, CURLOPT_POSTFIELDS, file_get_contents($credentials_file));
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);

    return [
        'status' => (int)$code,
        'body'   => $body === false ? '' : $body,
    ];
}


/* ========= JapanPost APIへプロキシ ========= */
function proxy_japanpost_api(string $token, string $search_code): void
{
    header('Content-Type: application/json');

    // 元コードの正規表現を関数化して判定
    $is_zip_or_code = is_zip_or_code($search_code);

    if ($is_zip_or_code) {
        // GET /searchcode/{search_code}
        $url = "https://api.da.pf.japanpost.jp/api/v1/searchcode/" . rawurlencode($search_code);

        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_USERAGENT, 'curl/' . curl_version()['version']);
        curl_setopt($ch, CURLOPT_HTTPHEADER, ["Authorization: Bearer $token"]);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

        $body = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);

        http_response_code((int)$code);
        echo $body;
        return;
    }

    // POST /addresszip
    $ch = curl_init('https://api.da.pf.japanpost.jp/api/v1/addresszip');
    curl_setopt($ch, CURLOPT_USERAGENT, 'curl/' . curl_version()['version']);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        "Authorization: Bearer $token",
        'Content-Type: application/json',
    ]);
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode(['freeword' => $search_code], JSON_UNESCAPED_UNICODE));
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);

    http_response_code((int)$code);
    echo $body;
}


/* ========= search_code 種別判定 ========= */
function is_zip_or_code(string $search_code): bool
{
    /**
     * 元コード：
     *   preg_match('/^\d{3,7}|\w{7}$/', $search_code)
     *
     * これは「^ が左側だけに効く」ので意図より広くマッチし得ます。
     * 元挙動を保つなら、そのまま。
     */
    return preg_match('/^\d{3,7}|\w{7}$/', $search_code) === 1;

    /**
     * もし “意図通りに厳密化” したい場合は、以下に置き換えてください：
     *
     * return preg_match('/^(\d{3,7}|\w{7})$/', $search_code) === 1;
     */
}

