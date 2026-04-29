# D-17: Bitwarden導入・認証情報移管ガイド

## 概要

チーム共有のパスワードマネージャーとしてBitwardenを導入し、現在個人で保管している認証情報を一元管理します。

## たとえ話で理解する

複数の鍵を全員がそれぞれの財布で管理していると、こんな問題が起きます:

- Aさんが退職→Aさんが知っていた鍵を全部変える必要がある（漏れリスク）
- 共有のパスワードをSlackに貼る→ログに残り続ける
- 担当者が休み→他の人が緊急対応できない

Bitwardenは「会社の金庫」のようなものです:
- 全員が同じ金庫にアクセス（権限管理付き）
- 退職時に1人分の鍵を取り上げるだけで済む
- 監査ログで「いつ誰が何を見たか」を追跡可能

## なぜBitwardenか

| 項目 | Bitwarden | 1Password | LastPass |
|------|-----------|-----------|----------|
| オープンソース | ✅ | ❌ | ❌ |
| セルフホスト可能 | ✅ | ❌ | ❌ |
| チーム機能（無料） | ✅ 2人まで | ❌ | ❌ |
| チーム機能（有料） | $4/user/月 | $7.99/user/月 | $4/user/月 |
| 過去のセキュリティ事故 | なし | なし | あり（2022年） |

→ **Bitwarden**を採用。オープンソースでセキュリティ実績が良好。

## 導入手順

### Phase 1: アカウント開設（しんごさん）

1. https://bitwarden.com/jp/ にアクセス
2. 「無料アカウントを作成」
3. 個人プランで開始（後でTeams Organizationに昇格）

### Phase 2: Organization作成

少人数（2人まで）なら**Free Organization**で十分です。

1. ログイン後、左メニュー「組織」→「新しい組織を作成」
2. 組織名: `Jarvis CRM Team`
3. プラン: `Free`（2ユーザーまで）
4. 「送信」

3人以上になる場合は **Teams Organization** ($4/user/月) に昇格してください。

### Phase 3: 移管する認証情報の整理

以下の認証情報をBitwardenに移行します:

#### サーバー・インフラ系
| 項目 | 現在の保管場所 | フォルダ |
|------|--------------|---------|
| さくらVPS コントロールパネル | （要確認） | Infra/Sakura |
| VPS SSH秘密鍵（hitoshi用） | ~/.ssh/ | Infra/SSH |
| VPS SSH秘密鍵（GitHub Actions用） | GitHub Secrets | Infra/SSH |
| sudoパスワード | （要確認） | Infra/Sakura |
| PostgreSQL `jarvis`ユーザーパスワード | VPS .env | Infra/Database |
| Redis パスワード | VPS .env | Infra/Database |

#### 外部サービス系
| 項目 | フォルダ |
|------|---------|
| GitHub（shingo-ops/salesanchor） | External/GitHub |
| GitHub Personal Access Token | External/GitHub |
| Cloudflare アカウント | External/Cloudflare |
| Cloudflare API トークン | External/Cloudflare |
| Firebase / GCP プロジェクト（sales-ops-with-claude） | External/GCP |
| Firebase Admin SDK 秘密鍵 | External/GCP |
| ドメイン管理（jarvis-claude.uk） | External/Domain |
| AWS アカウント（運用開始時） | External/AWS |
| AWS IAM `jarvis-backup` キー（運用開始時） | External/AWS |

#### アプリケーション系
| 項目 | フォルダ |
|------|---------|
| 管理者ユーザー（admin@example.com） | App/Admin |
| Grafana adminパスワード | App/Monitoring |
| テスト用ユーザー | App/Test |

### Phase 4: フォルダ構造（推奨）

```
Jarvis CRM Team
├── Infra/
│   ├── Sakura          # さくらVPSコンパネ・sudoパス
│   ├── SSH             # SSH秘密鍵
│   └── Database        # DB/Redisパスワード
├── External/
│   ├── GitHub
│   ├── Cloudflare
│   ├── GCP
│   ├── Domain
│   └── AWS             # 運用開始時に追加
├── App/
│   ├── Admin
│   ├── Monitoring
│   └── Test
└── Personal/           # 各メンバー個人用
```

### Phase 5: 権限設定

| ロール | 権限 |
|--------|------|
| Owner（しんごさん） | 全権限 |
| Admin（開発リード） | フォルダ作成・ユーザー追加 |
| User（一般メンバー） | 割り当てフォルダのみ閲覧・編集 |

ベストプラクティス:
- 開発メンバーには **App/** と **External/GitHub** のみ付与
- インフラ担当には **Infra/** と **External/Cloudflare, Domain** を付与
- AWS本番キーは **Owner と インフラ担当のみ**

### Phase 6: 移行後のチェック

- [ ] 全ての認証情報がBitwardenに登録されている
- [ ] 各メンバーがクライアントアプリ（Mac/iOS/Android）をインストール
- [ ] ブラウザ拡張機能をインストール
- [ ] 二要素認証（TOTP）を全メンバーで有効化
- [ ] マスターパスワードのリカバリーコードを安全に保管
- [ ] **個人のメモ・1Password・キーチェーンから該当認証情報を削除**

## 運用ルール（docs/B-11_credential_management_policy.md と連動）

### パスワード生成
- 全パスワードはBitwardenのジェネレーターで生成
- 最低16文字、英大小数字記号含む

### ローテーション
- 共有認証情報: 90日ごとにローテーション
- APIキー: 6ヶ月ごとにローテーション
- 退職・契約終了時: 即日ローテーション（docs/B-12_offboarding_procedure.md参照）

### 禁止事項
- ❌ Slackやメールでパスワードを共有
- ❌ 個人のメモ・スマホメモアプリへの保存
- ❌ ブラウザの「パスワードを保存」機能（個人ブラウザは可、共有用途は不可）
- ❌ Gitリポジトリへのコミット

## トラブルシューティング

### マスターパスワードを忘れた

→ **Bitwardenはゼロ知識暗号化なので復旧不可能**。
事前にリカバリーコードを安全な場所（紙に印刷して金庫など）に保管してください。

### チームメンバーがログインできない

→ Organization管理画面でユーザーステータスを確認。「招待中」のままなら招待メールを再送。

### 急ぎでパスワードが必要なのにBitwardenが落ちた

→ 各メンバーのローカルクライアントにキャッシュされているので、オフラインでも閲覧可能。

## 参考リンク

- 公式: https://bitwarden.com/jp/
- 価格: https://bitwarden.com/pricing/
- セキュリティホワイトペーパー: https://bitwarden.com/help/bitwarden-security-white-paper/
- セルフホスト手順: https://bitwarden.com/help/install-on-premise-linux/（将来検討用）
