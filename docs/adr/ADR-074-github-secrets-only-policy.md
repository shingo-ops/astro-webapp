# ADR-074: GitHub Secrets 一元管理ポリシー

- **Status**: Accepted
- **Date**: 2026-05-26
- **Author**: Claude Code (Hikky-dev)
- **PO**: しんごさん

---

## 背景

リポジトリ全体に「Bitwarden」への言及が散在していたが、実際には Bitwarden は導入・使用されておらず、
シークレット管理は一貫して GitHub Secrets のみで運用されていた。
ドキュメントと実態の乖離を解消し、シークレット管理の方針を一元化する。

---

## 決定

**本番環境のシークレットは GitHub Secrets のみで管理する。**

| 環境 | 保管場所 | 用途 |
|------|---------|------|
| 本番 | GitHub Secrets | CI/CD 経由で VPS `.env` に自動展開（`deploy.yml`） |
| 開発 | `.env`（`.gitignore` 除外済み） | ローカル開発・Docker Compose |
| 暗号化鍵バックアップ | GitHub Secrets 以外の安全な保管場所 | `METADATA_FERNET_KEY` 等、鍵紛失リスク対策 |

---

## 対象シークレット（GitHub Secrets 管理）

`deploy.yml` が参照する 10 件:

| Secret 名 | 用途 |
|-----------|------|
| `VPS_HOST` | VPS 接続先ホスト |
| `VPS_USER` | VPS SSH ユーザー |
| `VPS_SSH_KEY` | VPS SSH 秘密鍵 |
| `METADATA_FERNET_KEY` | テナントトークン暗号化鍵 |
| `POSTGRES_PASSWORD` | PostgreSQL パスワード |
| `META_APP_SECRET` | Meta（Facebook）App Secret |
| `DISCORD_BOT_TOKEN_*` | Discord Bot トークン |
| `GEMINI_API_KEY` | Gemini LLM API キー |
| `UPTIME_KUMA_URL` | 死活監視 Webhook URL |
| `ADMIN_NOTIFICATION_DISCORD_WEBHOOK` | 管理通知 Webhook |

---

## 理由

1. **実態との整合**: 既に GitHub Secrets のみで運用が確立されている（Bitwarden は未導入）
2. **CI/CD ネイティブ**: GitHub Actions の `${{ secrets.X }}` 構文で直接参照でき、追加ツール不要
3. **シンプルさ**: 別途パスワードマネージャーを導入・維持するコスト・複雑性を排除
4. **監査可能性**: GitHub の Secret 更新履歴・アクセスログで管理状態を追跡できる

---

## 検出・強制の仕組み

| 仕組み | 担当ファイル | 効果 |
|--------|------------|------|
| gitleaks CI（secret-scan.yml） | `.github/workflows/secret-scan.yml` | PR・push 時にシークレット平文埋め込みを自動検出してブロック |
| `.gitleaks.toml` カスタムルール | `.gitleaks.toml` | `METADATA_FERNET_KEY`・`META_APP_SECRET` 等のプロジェクト固有パターンを追加検出 |
| `deploy.yml` Secret 展開 | `.github/workflows/deploy.yml` | GitHub Secrets → VPS `.env` の自動反映（main マージ時） |

---

## 暗号化鍵の二重保管（セキュリティ要件）

`METADATA_FERNET_KEY` は Fernet 対称鍵。鍵を紛失すると全テナントの暗号化データが復号不能になる。
GitHub Secrets 障害・誤削除に備えて、**GitHub Secrets 以外の安全なバックアップ保管場所**（暗号化ファイル、オフライン vault 等）にも保管する。
詳細: `docs/operations/meta_encryption_key_rotation.md`

---

## 否定した選択肢

| 選択肢 | 否定理由 |
|--------|---------|
| AWS Secrets Manager | 追加コスト（~60円/月）よりも `deploy.yml` の複雑化（6〜8ステップ増）が問題。現状で十分 |
| Bitwarden（旧ドキュメントの推奨） | 未導入。GitHub Secrets で完結しており追加ツールは不要 |

---

## 関連

- `docs/B-11_credential_management_policy.md` — 認証情報管理ルール（本 ADR に基づき更新）
- `.github/workflows/secret-scan.yml` — gitleaks CI（ADR-074 と同時導入）
- `docs/operations/meta_encryption_key_rotation.md` — 暗号化鍵ローテーション手順
- ADR-025 — Meta 連携運用強化（`deploy.yml` による Secret 展開の起案）
