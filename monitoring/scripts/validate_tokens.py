#!/usr/bin/env python3
"""
monitoring/scripts/validate_tokens.py
======================================
監視スタック SSoT 整合性チェックスクリプト

【チェック内容】
  1. :latest タグ検出（監視サービス対象のみ）       → エラー（ブロック）
  2. tokens.yml バージョン vs docker-compose.yml    → エラー（ブロック）
  3. アラート閾値整合性チェック                      → 警告のみ（advisory）
  4. healthcheck 設定確認                           → 警告のみ（STEP4完了まで）

【終了コード】
  0 = 全チェック通過（警告は出ても OK）
  1 = エラーあり（CI ブロック）
"""

import sys
import re
import yaml

TOKENS_FILE = "monitoring/tokens.yml"
COMPOSE_FILE = "docker-compose.yml"
ALERT_RULES_FILE = "monitoring/prometheus/alert_rules.yml"

# tokens.yml の versions キー → docker-compose.yml のイメージプレフィックス
MONITORING_IMAGES = {
    "nginx":             "nginx",
    "certbot":           "certbot/certbot",
    "prometheus":        "prom/prometheus",
    "grafana":           "grafana/grafana",
    "loki":              "grafana/loki",
    "promtail":          "grafana/promtail",
    "node_exporter":     "prom/node-exporter",
    "postgres_exporter": "prometheuscommunity/postgres-exporter",
    "nginx_exporter":    "nginx/nginx-prometheus-exporter",
    "uptime_kuma":       "louislam/uptime-kuma",
    # ドリルダウン監視（ADR-079）
    # cadvisor: VPS cgroup 名前空間制限により無効化済み
    "redis_exporter":    "oliver006/redis_exporter",
}

# build: 方式のサービス: tokens.yml の versions キー → Dockerfile パス
# docker-compose image: タグではなく Dockerfile ARG で バージョンを管理
DOCKERFILE_VERSIONS = {
    "gha_exporter": "monitoring/gha-exporter/Dockerfile",
}

# healthcheck 確認対象の監視サービス
MONITORING_SERVICES = ["prometheus", "grafana", "loki", "promtail", "uptime-kuma"]

errors = []
warnings = []


def header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


# ── ファイル読み込み ──────────────────────────────────────────

try:
    with open(TOKENS_FILE) as f:
        tokens = yaml.safe_load(f)
except FileNotFoundError:
    print(f"❌ {TOKENS_FILE} が見つかりません（このファイルは必須です）")
    sys.exit(1)

with open(COMPOSE_FILE) as f:
    compose_text = f.read()

try:
    compose_data = yaml.safe_load(compose_text)
except yaml.YAMLError as e:
    print(f"❌ {COMPOSE_FILE} の YAML パースに失敗: {e}")
    sys.exit(1)

with open(ALERT_RULES_FILE) as f:
    alert_rules_text = f.read()


# ── CHECK 1: :latest タグ検出（監視サービス対象） ────────────

header("CHECK 1: :latest タグ（監視サービス対象のみ）")

for token_key, image_prefix in MONITORING_IMAGES.items():
    pattern = rf"image:\s+{re.escape(image_prefix)}:latest"
    if re.search(pattern, compose_text):
        errors.append(
            f":latest タグ検出 [{token_key}]: {image_prefix}:latest"
            f" → monitoring/tokens.yml の versions.{token_key} を使ってください"
        )
    else:
        print(f"  ✅ {image_prefix}: latest タグなし")


# ── CHECK 2: tokens.yml バージョン vs docker-compose.yml ─────

header("CHECK 2: tokens.yml バージョン整合性")

versions = tokens.get("versions", {})
for token_key, image_prefix in MONITORING_IMAGES.items():
    expected_ver = versions.get(token_key)
    if not expected_ver:
        warnings.append(
            f"tokens.yml に versions.{token_key} の定義がありません"
        )
        continue
    expected_tag = f"{image_prefix}:{expected_ver}"
    if expected_tag in compose_text:
        print(f"  ✅ {token_key}: {expected_tag}")
    else:
        errors.append(
            f"SSoT 不一致 [{token_key}]: "
            f"tokens.yml={expected_ver} が docker-compose.yml に見つかりません"
            f"（期待値: image: {expected_tag}）"
        )


# ── CHECK 3: アラート閾値整合性（advisory） ──────────────────

header("CHECK 3: アラート閾値整合性（警告のみ・advisory）")

threshold_checks = [
    # (tokens.yml キー, PromQL 検索パターン, アラート名)
    ("cpu_warning_pct",
     r"node_cpu_seconds_total[^>]+>\s*(\d+)",
     "HighCpuUsage"),
    ("memory_warning_pct",
     r"node_memory_MemAvailable_bytes[^>]+>\s*(\d+)",
     "HighMemoryUsage"),
    ("disk_warning_pct",
     r"node_filesystem_avail_bytes[^>]+>\s*(\d+)",
     "HighDiskUsage"),
    ("db_connection_warning",
     r"pg_stat_activity_count\s*>\s*(\d+)",
     "HighDbConnections"),
    ("nginx_5xx_per_5m",
     r'nginx_http_requests_total\{status=~"5\.\."\}\[5m\]\)\s*>\s*(\d+)',
     "HighErrorRate"),
    ("nginx_502_per_2m",
     r'nginx_http_requests_total\{status="502"\}\[2m\]\)\s*>\s*(\d+)',
     "High502Rate"),
]

thresholds = tokens.get("thresholds", {})
for token_key, pattern, alert_name in threshold_checks:
    expected = thresholds.get(token_key)
    if expected is None:
        continue
    m = re.search(pattern, alert_rules_text, re.DOTALL)
    if m:
        actual = int(m.group(1))
        if actual == expected:
            print(f"  ✅ {alert_name}: {expected}")
        else:
            warnings.append(
                f"閾値ズレ [{alert_name}]: "
                f"tokens.yml={expected}, alert_rules.yml={actual}"
            )
    else:
        print(f"  ℹ️  {alert_name}: パターン未マッチ（スキップ）")


# ── CHECK 4: healthcheck 設定（WARNING MODE） ─────────────────

header("CHECK 4: healthcheck 設定（警告のみ・STEP4完了まで）")

services = compose_data.get("services", {})
for svc in MONITORING_SERVICES:
    if svc not in services:
        warnings.append(f"{svc}: docker-compose.yml にサービス定義が見つかりません")
    elif "healthcheck" not in services[svc]:
        warnings.append(
            f"{svc}: healthcheck が未設定です"
            f"（PR #889 がマージされると解消されます）"
        )
    else:
        print(f"  ✅ {svc}: healthcheck 設定済み")


# ── CHECK 5: Dockerfile バージョン整合性（build: 方式サービス）─

header("CHECK 5: Dockerfile バージョン整合性（build: 方式サービス）")

for token_key, dockerfile_path in DOCKERFILE_VERSIONS.items():
    expected_ver = versions.get(token_key)
    if not expected_ver:
        warnings.append(f"tokens.yml に versions.{token_key} の定義がありません")
        continue
    try:
        with open(dockerfile_path) as f:
            dockerfile_text = f.read()
    except FileNotFoundError:
        errors.append(f"Dockerfile が見つかりません: {dockerfile_path}")
        continue
    # ARG GHA_EXPORTER_VERSION=v0.0.15 形式を検索
    arg_pattern = rf"ARG\s+\w+VERSION\s*=\s*{re.escape(expected_ver)}"
    if re.search(arg_pattern, dockerfile_text):
        print(f"  ✅ {token_key}: Dockerfile ARG = {expected_ver}")
    else:
        errors.append(
            f"SSoT 不一致 [{token_key}]: "
            f"tokens.yml={expected_ver} が {dockerfile_path} の ARG に見つかりません"
        )


# ── 結果サマリー ──────────────────────────────────────────────

header("結果サマリー")

if warnings:
    print(f"\n⚠️  警告 {len(warnings)} 件（ブロックしません）:")
    for w in warnings:
        print(f"  • {w}")

if errors:
    print(f"\n❌ エラー {len(errors)} 件（CI ブロック）:")
    for e in errors:
        print(f"  • {e}")
    print(f"\n→ {len(errors)} 件のエラーを修正してください。")
    sys.exit(1)

print(f"\n✅ 全チェック通過（警告 {len(warnings)} 件）")
sys.exit(0)
