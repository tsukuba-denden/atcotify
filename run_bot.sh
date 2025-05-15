#!/bin/bash

# プロジェクトディレクトリに移動
cd /home/yuubinnkyoku/atcotify/

# certifi のパスを取得 (毎回最新を確認する場合)
CERT_PATH=$(uv run test.py)
# または固定パスを指定
# CERT_PATH="/home/yuubinnkyoku/atcotify/.venv/lib/python3.12/site-packages/certifi/cacert.pem"

# 環境変数を設定
export SSL_CERT_FILE="$CERT_PATH"
export REQUESTS_CA_BUNDLE="$CERT_PATH"

# プログラムを実行
echo "Starting bot with SSL_CERT_FILE=$SSL_CERT_FILE"
nohup uv run main.py &
