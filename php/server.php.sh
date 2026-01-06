#!/bin/zsh
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
SHARED_FRONTEND="$PROJECT_ROOT/shared/frontend"

PORT=${1:-8000}
HOST=127.0.0.1
URL="http://$HOST:$PORT/?search_code=1000001"
INDEX="http://$HOST:$PORT/index.html"

PATH="/opt/homebrew/opt/php@8.4/bin:$PATH"
PATH="/opt/homebrew/opt/php@8.4/sbin:$PATH"

servephp() {
  local port=${1:-8000}
  php -S 127.0.0.1:$port -t "$SCRIPT_DIR" "$SCRIPT_DIR/index.php"
}

# サーバ停止処理（Ctrl+C / kill / 終了時に必ず呼ばれる）
cleanup() {
  echo "\n[server.php.sh] Stopping PHP server..."
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID"
    wait "$SERVER_PID" 2>/dev/null || true
    echo "[server.php.sh] Stopped. (pid=$SERVER_PID)"
  fi
}

# EXIT / INT(Ctrl+C) / TERM を捕捉して cleanup を実行
trap cleanup EXIT INT TERM

echo "[server.php.sh] Starting PHP server on $URL ..."

# 必要な共有ディレクトリの存在を案内
if [[ ! -f "$SHARED_FRONTEND/index.html" ]]; then
  echo "[server.php.sh] Warning: $SHARED_FRONTEND/index.html が見つかりません。"
fi

mkdir -p "$PROJECT_ROOT/shared/runtime"

# servephp はフォアグラウンドで動くので、バックグラウンドで起動
servephp "$PORT" >/dev/null 2>&1 &
SERVER_PID=$!

# サーバが立ち上がるのを軽く待つ（早すぎるopen対策）
sleep 0.3

echo "[server.php.sh] Opening browser..."
open "$INDEX"

echo "[server.php.sh] PHP server is running (pid=$SERVER_PID)."
echo "[server.php.sh] Press Ctrl+C to stop."

# サーバが終わるまで待つ（これがあるのでスクリプトが即終了しない）
wait "$SERVER_PID"

