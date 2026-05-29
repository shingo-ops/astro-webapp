#!/usr/bin/env python3
"""
monitoring/scripts/validate_tokens.py
======================================
監視スタック SSoT 整合性チェックスクリプト

【チェック内容】
  1. :latest タグ検出（監視/周辺 compose 対象）   → エラー（ブロック）
  2. tokens.yml バージョン vs compose files        → エラー（ブロック）
  3. アラート閾値整合性チェック                    → 警告のみ（advisory）
  4. healthcheck 設定確認                         → 警告のみ（advisory）
  5. Dockerfile バージョン整合性（build: 方式）   → エラー（ブロック）

【終了コード】
  0 = 全チェック通過（警告は出ても OK）
  1 = エラーあり（CI ブロック）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

TOKENS_FILE = Path("monitoring/tokens.yml")
ALERT_RULES_FILE = Path("monitoring/prometheus/alert_rules.yml")
COMPOSE_FILES = [
    Path("docker-compose.yml"),
    Path("docker-compose.monitoring.yml"),
    Path("docker-compose.exporters.yml"),
]

# tokens.yml の versions キー → compose files のイメージプレフィックス
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
DOCKERFILE_VERSIONS = {
    "gha_exporter": Path("monitoring/gha-exporter/Dockerfile"),
}

# healthcheck 確認対象の監視サービス
MONITORING_SERVICES = [
    "prometheus",
    "grafana",
    "node-exporter",
    "gha-exporter",
    "loki",
    "uptime-kuma",
    "postgres-exporter",
    "nginx-exporter",
    "redis-exporter",
    "promtail",
]

errors: list[str] = []
warnings: list[str] = []


def header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def read_text(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        errors.append(f"必要なファイルが見つかりません: {path}")
        return ""


def load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        errors.append(f"必要なファイルが見つかりません: {path}")
        return {}
    except yaml.YAMLError as exc:
        errors.append(f"{path} の YAML パースに失敗: {exc}")
        return {}


# ── ファイル読み込み ──────────────────────────────────────────

try:
    tokens = yaml.safe_load(TOKENS_FILE.read_text()) or {}
except FileNotFoundError:
    print(f"❌ {TOKENS_FILE} が見つかりません（このファイルは必須です）")
    sys.exit(1)
except yaml.YAMLError as exc:
    print(f"❌ {TOKENS_FILE} の YAML パースに失敗: {exc}")
    sys.exit(1)

compose_texts: list[str] = []
compose_docs: list[tuple[Path, dict]] = []
for compose_file in COMPOSE_FILES:
    compose_text = read_text(compose_file)
    if compose_text:
        compose_texts.append(compose_text)
        compose_docs.append((compose_file, load_yaml(compose_file)))

compose_text = "\n\n".join(compose_texts)

try:
    alert_rules_text = ALERT_RULES_FILE.read_text()
except FileNotFoundError:
    print(f"❌ {ALERT_RULES_FILE} が見つかりません（このファイルは必須です）")
    sys.exit(1)


# ── CHECK 1: :latest タグ検出（監視サービス対象） ────────────

header("CHECK 1: :latest タグ（compose files 対象のみ）")

for token_key, image_prefix in MONITORING_IMAGES.items():
    pattern = rf"image:\s+{re.escape(image_prefix)}:latest"
    if re.search(pattern, compose_text):
        errors.append(
            f":latest タグ検出 [{token_key}]: {image_prefix}:latest"
            f" → monitoring/tokens.yml の versions.{token_key} を使ってください"
        )
    else:
        print(f"  ✅ {image_prefix}: latest タグなし")


# ── CHECK 2: tokens.yml バージョン vs compose files ─────────

header("CHECK 2: tokens.yml バージョン整合性")

versions = tokens.get("versions", {})
for token_key, image_prefix in MONITORING_IMAGES.items():
    expected_ver = versions.get(token_key)
    if not expected_ver:
        warnings.append(f"tokens.yml に versions.{token_key} の定義がありません")
        continue
    expected_tag = f"{image_prefix}:{expected_ver}"
    if expected_tag in compose_text:
        print(f"  ✅ {token_key}: {expected_tag}")
    else:
        errors.append(
            f"SSoT 不一致 [{token_key}]: "
            f"tokens.yml={expected_ver} が compose files に見つかりません"
            f"（期待値: image: {expected_tag}）"
        )


# ── CHECK 3: アラート閾値整合性（advisory） ──────────────────

header("CHECK 3: アラート閾値整合性（警告のみ・advisory）")

threshold_checks = [
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
    match = re.search(pattern, alert_rules_text, re.DOTALL)
    if match:
        actual = int(match.group(1))
        if actual == expected:
            print(f"  ✅ {alert_name}: {expected}")
        else:
            warnings.append(
                f"閾値ズレ [{alert_name}]: "
                f"tokens.yml={expected}, alert_rules.yml={actual}"
            )
    else:
        print(f"  ℹ️  {alert_name}: パターン未マッチ（スキップ）")


# ── CHECK 4: healthcheck 設定（advisory） ───────────────────

header("CHECK 4: healthcheck 設定（警告のみ・advisory）")

services = {}
service_sources: dict[str, list[Path]] = {}
for compose_file, compose_data in compose_docs:
    file_services = compose_data.get("services", {})
    for service_name, service_def in file_services.items():
        services.setdefault(service_name, service_def)
        service_sources.setdefault(service_name, []).append(compose_file)

for svc in MONITORING_SERVICES:
    if svc not in services:
        warnings.append(f"{svc}: compose files にサービス定義が見つかりません")
        continue
    if "healthcheck" not in services[svc]:
        warnings.append(
            f"{svc}: healthcheck が未設定です"
            f"（compose file: {', '.join(str(p) for p in service_sources.get(svc, []))}）"
        )
    else:
        print(
            f"  ✅ {svc}: healthcheck 設定済み"
            f"（compose file: {', '.join(str(p) for p in service_sources.get(svc, []))}）"
        )


# ── CHECK 5: Dockerfile バージョン整合性（build: 方式）───────

header("CHECK 5: Dockerfile バージョン整合性（build: 方式サービス）")

for token_key, dockerfile_path in DOCKERFILE_VERSIONS.items():
    expected_ver = versions.get(token_key)
    if not expected_ver:
        warnings.append(f"tokens.yml に versions.{token_key} の定義がありません")
        continue
    try:
        dockerfile_text = dockerfile_path.read_text()
    except FileNotFoundError:
        errors.append(f"Dockerfile が見つかりません: {dockerfile_path}")
        continue
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
    for warning in warnings:
        print(f"  • {warning}")

if errors:
    print(f"\n❌ エラー {len(errors)} 件（CI ブロック）:")
    for error in errors:
        print(f"  • {error}")
    print(f"\n→ {len(errors)} 件のエラーを修正してください。")
    sys.exit(1)

print(f"\n✅ 全チェック通過（警告 {len(warnings)} 件）")
sys.exit(0)
