# Firebase Authentication カスタム認証ドメイン セットアップ手順

| 項目 | 内容 |
|---|---|
| 関連 ADR | [ADR-032](./adr/ADR-032.md) |
| 対象ドメイン | `auth.salesanchor.jp` |
| 旧ドメイン | `sales-ops-with-claude.firebaseapp.com`（並行維持） |
| 実施者 | しんごさん（PO、本番アクセス権限保持） |
| 所要時間 | 30〜60 分（DNS / SSL 反映 最大 48 時間） |

---

## 0. なぜこの作業が必要か（背景）

### 切り替える理由

Sales Anchor の OAuth フロー（Facebook Login など）でユーザーに見える URL は、現状 `sales-ops-with-claude.firebaseapp.com` という Firebase の自動生成ドメイン。

- Meta App Review レビュアーや本番ユーザーに **「sales-ops-with-claude」というプロジェクト ID が露出**してしまう
- 撮影本番（Meta App Review screencast）でブランド統一が崩れる
- `salesanchor.jp` に統一したいが、Firebase Project ID 自体の変更は 9〜18 時間 + 高リスク

### この対応で何が変わるか

```
変更前: https://sales-ops-with-claude.firebaseapp.com/__/auth/handler?...
変更後: https://auth.salesanchor.jp/__/auth/handler?...
```

ユーザー体験はほぼ変わらない（OAuth ポップアップに表示される URL のドメイン部だけが Sales Anchor ブランドになる）。

### スコープ外（やらないこと）

- Firebase Project ID の変更（撮影後に ADR-031 で対応）
- Firebase Hosting でアプリ本体（React 本体）をホスティング → **認証用途のみ**
- Firestore / Storage 等 他 Firebase プロダクトのドメイン変更

---

## 1. 全体フロー

```
[A] DNS レコード追加 (Cloudflare)
        │ 反映 5 分〜数時間
        ▼
[B] Firebase Hosting にカスタムドメイン追加
        │ 自動 SSL 証明書発行 最大 24 時間
        ▼
[C] Firebase Authentication の Authorized domains に追加
        │
        ▼
[D] Meta Developer Portal に新 Redirect URI 追加（旧 URI は残す）
        │
        ▼
[E] 環境変数を切り替えて frontend を再ビルド・デプロイ
        │
        ▼
[F] 動作確認（受け入れ基準 1〜5）
```

---

## 2. [A] Cloudflare DNS にレコード追加

1. Cloudflare ダッシュボード → `salesanchor.jp` ゾーンを開く
2. **DNS > Records > Add record**
3. 以下のレコードを追加（Firebase Hosting が指定する A/CNAME 値は手順 [B] の途中で表示されるため、ここでは一旦スキップ可）

> 💡 順序のコツ: 先に Firebase Hosting 側でカスタムドメイン追加を始めると、Firebase が「このレコードを追加してください」と具体的な値を出してくれる。それをコピペして Cloudflare に登録する流れが最も確実。

---

## 3. [B] Firebase Hosting にカスタムドメイン追加

> ⚠ Firebase Hosting で **アプリをホスティングはしない**。Firebase Auth の `__/auth/handler` を `auth.salesanchor.jp` で配信させるためだけに Hosting を有効化する。

### 3-1. Firebase Console を開く

1. https://console.firebase.google.com/ → プロジェクト `sales-ops-with-claude` を選択
2. 左メニュー **Build > Hosting** をクリック
3. （初回のみ）**Get started** → 案内に従って初期化（CLI 操作は不要、ダッシュボードから完結する）

### 3-2. カスタムドメインを追加

1. **Add custom domain** をクリック
2. ドメイン入力欄に `auth.salesanchor.jp` を入力 → **Continue**
3. Firebase が DNS レコード（A レコード or CNAME）を提示する → **手順 [A] に戻って Cloudflare に登録**
4. Firebase ダッシュボードに戻り **Verify** をクリック
5. ドメイン所有権の確認後、**自動で SSL 証明書がプロビジョニング**される（最大 24 時間、通常は数分〜1 時間）

### 3-3. 状態確認

- ダッシュボードで `auth.salesanchor.jp` のステータスが **Connected** になれば OK
- ブラウザで https://auth.salesanchor.jp/ を開いて、Firebase Hosting のデフォルトページ（または 404）が SSL で表示されれば SSL 発行完了

---

## 4. [C] Firebase Authentication の Authorized domains に追加

1. Firebase Console → **Authentication > Settings** タブ
2. **Authorized domains** セクション → **Add domain**
3. `auth.salesanchor.jp` を入力 → **Add**
4. **既存の `sales-ops-with-claude.firebaseapp.com` は削除しない**（ADR-032 「既存ドメイン併用」要件 + 切り戻し用の保険）

詳細は [`docs/FIREBASE_API_KEY_RESTRICTION_GUIDE.md` §2-3](./FIREBASE_API_KEY_RESTRICTION_GUIDE.md) も併読。

---

## 5. [D] Meta Developer Portal に新 Redirect URI を追加

> ⚠ **既存の Redirect URI は絶対に削除しない**（撮影中の障害回避 / ADR-032 事業上の制約）。新しい URI を「追加」するだけ。

### 5-1. Facebook Login の設定画面を開く

1. https://developers.facebook.com/ → 該当アプリを選択
2. **Products > Facebook Login > Settings**
3. **Valid OAuth Redirect URIs** セクションを確認

### 5-2. 新 URI を追加

以下の URI を **追加**（既存の `sales-ops-with-claude.firebaseapp.com` 系は残す）:

```
https://auth.salesanchor.jp/__/auth/handler
```

> 💡 Firebase Auth が Facebook Login にリダイレクトするときに使うハンドラ URL。`/__/auth/handler` は Firebase Hosting が自動配信するエンドポイント。

### 5-3. Save Changes をクリック

---

## 6. [E] 環境変数の切り替え

### 6-1. VPS の `.env` を更新

```bash
ssh ubuntu@49.212.137.46
cd /home/ubuntu/salesanchor
sudo vi .env
```

以下を変更:

```env
# 切替前
FIREBASE_AUTH_DOMAIN=sales-ops-with-claude.firebaseapp.com
VITE_FIREBASE_AUTH_DOMAIN=sales-ops-with-claude.firebaseapp.com

# 切替後（ADR-032）
FIREBASE_AUTH_DOMAIN=auth.salesanchor.jp
VITE_FIREBASE_AUTH_DOMAIN=auth.salesanchor.jp
```

### 6-2. frontend を再ビルド・再起動

```bash
cd /home/ubuntu/salesanchor
sudo docker compose build frontend
sudo docker compose up -d frontend
```

> ⚠ Vite はビルド時に `import.meta.env.VITE_*` を埋め込むため、env を変えただけでは反映されない。**必ず再ビルド**。

### 6-3. 切り戻し手順（必要時）

トラブル発生時は env を旧値に戻して再ビルドするだけで切り戻し可能:

```env
FIREBASE_AUTH_DOMAIN=sales-ops-with-claude.firebaseapp.com
VITE_FIREBASE_AUTH_DOMAIN=sales-ops-with-claude.firebaseapp.com
```

```bash
sudo docker compose build frontend && sudo docker compose up -d frontend
```

旧ドメインは Authorized domains / Meta Redirect URI 共に残置されているため、即座に動作復帰する。

---

## 7. [F] 動作確認（ADR-032 受け入れ基準 1〜5）

| # | 受け入れ基準 | 確認方法 |
|---|---|---|
| 1 | `auth.salesanchor.jp` で Firebase Authentication が動作 | シークレットウィンドウで https://app.salesanchor.jp/ → ログイン → 認証成功すること |
| 2 | 新規ログインで OAuth URL が `auth.salesanchor.jp` 経由 | DevTools > Network で identitytoolkit / `/__/auth/handler` のリクエスト URL が `auth.salesanchor.jp` になっていることを確認 |
| 3 | 既存ログインセッションが壊れていない | 既存ユーザーで再ログイン不要のままアクセス → 認証エラーなく開けること |
| 4 | 既存ユーザーが再ログイン後、正常動作 | ログアウト → 再ログイン → 顧客一覧 / Inbox 等の主要画面が正常表示 |
| 5 | Meta OAuth が新ドメインで成功 | `/channels` から Meta 接続フロー → Facebook ログインポップアップの URL に `auth.salesanchor.jp` が含まれる → 接続完了まで通る |

> 受け入れ基準 6（環境変数で旧ドメインへの切り戻しが可能）は §6-3 の手順で担保済み。実機切り戻しテストは撮影前夜などのリスクがない時間帯に 1 度通しておくのが安全。

---

## 8. トラブルシューティング

### 症状: `auth/unauthorized-domain` エラー

**原因**: Firebase Authentication の Authorized domains に `auth.salesanchor.jp` が未登録。

**対処**: §4 を再確認。反映に数分かかることがある。

### 症状: SSL 証明書エラー（NET::ERR_CERT_*）

**原因**: Firebase Hosting の SSL 自動発行が未完了。

**対処**: 最大 24 時間待つ。Firebase Console の Hosting ダッシュボードでステータスが "Connected" / "SSL active" になるまで待機。

### 症状: Meta OAuth で `URL Blocked` エラー

**原因**: Meta Developer Portal の Valid OAuth Redirect URIs に `https://auth.salesanchor.jp/__/auth/handler` が未登録。

**対処**: §5 を再確認。Save Changes 押下後 1〜2 分で反映。

### 症状: env 変更したのに古いドメインで OAuth が走る

**原因**: frontend コンテナの再ビルド忘れ。

**対処**: `sudo docker compose build frontend && sudo docker compose up -d frontend` を実行。`docker compose restart frontend` だけでは旧ビルド成果物のままなので不可。

---

## 9. 実施記録

作業完了後、`docs/INTERNAL_TEST_RECORD.md` または該当 PR 本文に以下を記録:

```markdown
## ADR-032 カスタム認証ドメイン切替実施記録
- 実施日: ____/__/__
- 実施者: ____________
- DNS 設定 (Cloudflare): ☐ 完了
- Firebase Hosting カスタムドメイン: ☐ Connected / ☐ SSL 発行済
- Firebase Authorized domains 追加: ☐ 完了 / ☐ 旧ドメイン残置確認
- Meta Developer Portal Redirect URI 追加: ☐ 完了 / ☐ 旧 URI 残置確認
- 環境変数切替 + 再ビルド: ☐ 完了
- 受け入れ基準 1〜5 確認: ☐ 全 PASS
- 切り戻しテスト: ☐ 実施済（旧 env で動作確認）
```

---

## 10. 関連ドキュメント

- ADR: [`docs/adr/ADR-032.md`](./adr/ADR-032.md)
- 環境変数リファレンス: [`docs/ENVIRONMENT_VARIABLES.md`](./ENVIRONMENT_VARIABLES.md) §2 / §3
- Firebase API Key 制限ガイド: [`docs/FIREBASE_API_KEY_RESTRICTION_GUIDE.md`](./FIREBASE_API_KEY_RESTRICTION_GUIDE.md)
- 撮影前チェックリスト: [`docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md`](./META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md)
