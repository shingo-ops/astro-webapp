#!/bin/sh
# GHA_APP_KEY_FILE が設定されている場合、ファイルから秘密鍵を読み込んで
# GHA_APP_KEY 環境変数にセットしてから gha-exporter を起動する。
# 秘密鍵を .env に直接書かずファイルマウントで管理するための薄いラッパー。
set -e

if [ -n "${GHA_APP_KEY_FILE:-}" ] && [ -f "${GHA_APP_KEY_FILE}" ]; then
    GHA_APP_KEY="$(cat "${GHA_APP_KEY_FILE}")"
    export GHA_APP_KEY
fi

exec gha-exporter "$@"
