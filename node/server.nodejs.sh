#!/bin/zsh
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

if [[ ! -d node_modules ]]; then
  echo "[server.nodejs.sh] Installing dependencies..."
  npm install
fi

npm start

