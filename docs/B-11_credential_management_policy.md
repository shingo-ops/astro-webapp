# B-11: 認証情報管理ルール

## 目的
パスワード・APIキー等の認証情報を安全に管理するためのルールを定める。

## 最終更新: 2026-05-26

**設計根拠**: ADR-075（GitHub Secrets 一元管理ポリシー）

---

## 基本ルール

### 1. シークレット管理の方針

**本番環境のシークレットは GitHub Secrets で一元管理する。**

| 環境 | 保管場所 | 共有方法 |
|------|---------|---------|
| 本番 | GitHub Secrets | CI/CD（`deploy.yml`）経由で VPS `.env` に自動展開 |
| 開発 | `.env`（`.gitignore` 除外済み） | PO（しんごさん）から直接受け取る |

**禁止事項:**
- テキストファイル・スプレッドシートでの管理
- 個人のメモアプリへの保存
- Slack / メール / チャットでのシークレット送信
- `.env` ファイルの Git コミット

### 2. パスワードポリシー

| 項目 | ルール |
|------|--------|
| 最小長 | 16文字以上 |
| 構成 | 英大文字 + 英小文字 + 数字 + 記号 |
| 生成方法 | パスワードマネージャーのランダム生成を使用 |
| 使い回し | 禁止（すべてのサービスで異なるパスワード） |
| 変更頻度 | 90日ごと、または漏洩の兆候があった場合即座に |

### 3. 管理対象の認証情報

| 種類 | 保管場所 | 共有方法 |
|------|---------|---------|
| VPS SSH秘密鍵 | GitHub Secrets（`VPS_SSH_KEY`） | GitHub Actions 経由でのみ使用 |
| PostgreSQL パスワード | GitHub Secrets（`POSTGRES_PASSWORD`）+ 開発 `.env` | PO から直接受け取る |
| Firebase サービスアカウントキー | GitHub Secrets + VPS上のファイル | PO から直接受け取る |
| GitHub Personal Access Token | 個人設定 | 共有しない（個人発行） |
| Cloudflare APIキー | GitHub Secrets | PO から直接受け取る |
| Grafana管理者パスワード | GitHub Secrets + 開発 `.env` | PO から直接受け取る |
| AWS IAMキー（S3バックアップ用） | GitHub Secrets + VPS環境変数 | PO から直接受け取る |
| METADATA_FERNET_KEY | GitHub Secrets + **別の安全なバックアップ保管場所** | PO から直接受け取る |

> **METADATA_FERNET_KEY の二重保管について**: この鍵を紛失すると全テナントの暗号化データが復号不能になる。
> GitHub Secrets 以外にも安全なバックアップ保管場所（暗号化ファイル、オフライン vault 等）に保管すること。
> 詳細: `docs/operations/meta_encryption_key_rotation.md`

### 4. .envファイルの取扱い

- `.env` ファイルは **絶対にGitにコミットしない**（.gitignoreで除外済み）
- 本番の `.env` はVPS上でのみ管理（`deploy.yml` が GitHub Secrets から自動展開）
- 新メンバーへの `.env` 共有は PO（しんごさん）経由のみ

### 5. APIキー・トークンのローテーション

| キー種別 | ローテーション頻度 |
|---------|------------------|
| Firebase サービスアカウントキー | 6ヶ月ごと |
| GitHub Deploy Key | 6ヶ月ごと |
| AWS IAMキー | 90日ごと |
| Grafana管理者パスワード | 90日ごと |

---

## セットアップ手順（新メンバー向け）

1. PO（しんごさん）から開発用 `.env` ファイルを受け取る
2. SSH鍵ペアを新規生成し、公開鍵をVPS管理者（PO）に送付
3. 個人 GitHub アカウントにリポジトリへのアクセス権限を付与してもらう
4. MFA（2要素認証）を GitHub アカウントに設定（必須）

---

## シークレット漏洩検出の仕組み

- **gitleaks CI**: PR・develop/main へのプッシュ時に自動スキャン（`.github/workflows/secret-scan.yml`）
- **カスタムルール**: `METADATA_FERNET_KEY`・`META_APP_SECRET` 等のプロジェクト固有パターンを検出（`.gitleaks.toml`）

---

## 禁止事項（まとめ）

- パスワードの平文保存・平文送信
- 個人アカウント（Gmail等）での業務用認証情報の保管
- 共有パスワードの使用（個人ごとにアカウントを発行する）
- `.env` ファイルのメール添付
- `sakura-vps-password.txt` のようなファイルをプロジェクトディレクトリに置くこと
- シークレット値をコード・ドキュメントに平文で記載すること
