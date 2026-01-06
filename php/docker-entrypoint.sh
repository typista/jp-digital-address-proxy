#!/bin/sh
set -eu

# Host側で公開されるポート。未設定なら 8000 を表示（php/ ディレクトリの compose 用）。
HOST_PORT="${PHP_HOST_PORT:-8000}"
HOST_ADDR="${PHP_HOST_ADDR:-127.0.0.1}"
PUBLIC_URL="http://${HOST_ADDR}:${HOST_PORT}"

echo "[php-proxy] Listening inside container on 0.0.0.0:8000"
echo "[php-proxy] Access from host via ${PUBLIC_URL}/"

exec php -S 0.0.0.0:8000 -t /app/php /app/php/index.php
