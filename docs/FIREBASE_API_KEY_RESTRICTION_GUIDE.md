# Firebase / Google Cloud API Key 制限設定ガイド

**目的**: ブラウザに公開される Firebase Web API Key が第三者に悪用されないよう、**利用元ドメインを制限**する。
**所要時間**: 約15分
**実施者**: しんごさん or hitoshiさん（Mac側のブラウザで実施）
**実施タイミング**: 本番公開前に必須、内部テスト前に済ませておくのが望ましい

---

## 0. なぜこの作業が必要か（前提の整理）

### Firebase Web API Key はそもそも公開される

```
ブラウザが https://jarvis-claude.uk を開く
      │
      ▼
index-XXXX.js をダウンロード
      │
      ▼
JSの中に AIzaSy... の文字列がそのまま埋め込まれている
      │
      ▼
F12 で開発者ツールを開けば誰でも見れる
```

**これは Firebase の設計上の仕様**。パスワードのような秘密情報ではない。

### ではどうやって守るか？

**「このキーは jarvis-claude.uk からしか使えない」という制限をGoogle側に登録する**。

たとえ話:
> クレジットカードは番号が見えていても、「◯◯店でしか使えない」と銀行に登録しておけば安全。Google Cloud / Firebase の設定も同じ発想。

### 制限しないとどうなるか

| シナリオ | 影響 |
|---------|------|
| 第三者が悪意のサイトで同じキーを使う | そのサイトから Firebase Auth で新規ユーザーを勝手に作られる |
| ブルートフォース攻撃に使われる | Firebase の無料枠を使い切られて課金発生 |
| 類似ドメイン（phishing）に使われる | ユーザーが偽サイトで認証してしまう |

---

## 1. 作業① Google Cloud Console で API Key 制限

### 1-1. アクセス

1. ブラウザで https://console.cloud.google.com/ を開く
2. 画面上部のプロジェクト選択で **「sales-ops-with-claude」** を選択
3. 左メニューから **「APIs & Services」** → **「Credentials」** をクリック

### 1-2. 対象キーの確認

「API Keys」セクションにキー一覧が表示される。
名前に **「Browser key (auto created by Firebase)」** または **「Web API Key」** のような名前のキーがあるはず。

**先頭文字確認**: 値が `AIzaSyAuk8...` で始まるものが対象（末尾の「︙」→「Show key」で確認可能）

### 1-3. アプリケーション制限の設定

対象キーの **鉛筆アイコン（Edit）** をクリック。

**「Application restrictions」** セクション:

```
○ None
○ Websites    ← これを選択
○ IP addresses
○ Android apps
○ iOS apps
```

**「Website restrictions」** に以下を追加:

| 許可するドメイン | 用途 |
|---------------|------|
| `https://app.salesanchor.jp/*` | 本番アプリ |
| `https://auth.salesanchor.jp/*` | ADR-032 カスタム認証ドメイン（Firebase Auth handler） |
| `https://jarvis-claude.uk/*` | レガシー本番（並行稼働中） |
| `https://*.jarvis-claude.uk/*` | サブドメイン（ステージング等予備） |

**⚠️ Google Cloud の入力ルール**:
- 末尾の `/*` は必須
- **ポートワイルドカード `:*` は使えない**（具体値が必要: `:5173/*` など）
- **IPアドレス（`127.0.0.1` 等）は登録不可**
- `localhost` を登録する場合は `http://localhost:5173/*` のようにポート指定
- Cloudflare 経由でも `*.cloudflare.com` 等は追加不要（設計上不要）

**ローカル開発用キーについて（推奨運用）**:
- 本番用キーに `localhost` を追加しない（攻撃者がローカル偽装で抜け穴化するリスク）
- ローカル開発時は以下のいずれかで対応:
  - (A) Firebase プロジェクトを開発用に別途作成
  - (B) Google Cloud Console で別の API Key を作り、制限を `http://localhost:5173/*` のみに
  - (C) 開発時のみ一時的に本番キーの制限を外す（非推奨）

### 1-4. API 制限の設定（任意だが推奨）

同じ編集画面の下部 **「API restrictions」** セクション:

```
○ Don't restrict key
○ Restrict key    ← これを選択
```

「Select APIs」で以下のみチェック:
- ✅ Identity Toolkit API（Firebase Auth が使う）
- ✅ Token Service API（JWT発行）
- ✅ Firebase Installations API（Firebaseクライアント初期化）

不要な API（Maps, Translate 等）がチェックされていたら外す。

### 1-5. 保存

画面下部の **「SAVE」** をクリック。**反映まで最大5分**かかる。

---

## 2. 作業② Firebase Console で承認済みドメイン制限

### 2-1. アクセス

1. ブラウザで https://console.firebase.google.com/ を開く
2. プロジェクト **「sales-ops-with-claude」** を選択
3. 左メニューの **「プロジェクト ショートカット」セクションにある「Authentication」**（人型アイコン）をクリック
   - ※ 旧UIでは「Build」→「Authentication」だったが、現在のUIでは「プロジェクト ショートカット」直下
   - ショートカットに無い場合は、左メニュー下部の「プロダクトのカテゴリ」→「ビルド」を展開
4. 上部タブ **「Settings」** をクリック
5. **「Authorized domains」（承認済みドメイン）** セクションを確認

### 2-2. 現状確認

初期状態では以下が自動登録されているはず:

- `localhost`
- `sales-ops-with-claude.firebaseapp.com`
- `sales-ops-with-claude.web.app`
- `jarvis-claude.uk` （追加済みなら）

### 2-3. 必要なドメインの追加・不要なドメインの削除

**残すもの**:
| ドメイン | 理由 |
|---------|------|
| `app.salesanchor.jp` | 本番アプリ |
| `auth.salesanchor.jp` | ADR-032 カスタム認証ドメイン（OAuth 表示用） |
| `jarvis-claude.uk` | レガシー本番（並行稼働中） |
| `localhost` | ローカル開発 |
| `sales-ops-with-claude.firebaseapp.com` | Firebase内部で使用 + ADR-032 切り戻し用に残置 |

**削除候補**:
- 過去のテスト用ドメイン
- 使っていないカスタムドメイン
- `sales-ops-with-claude.web.app`（Firebase Hosting で `auth.salesanchor.jp` のみ使う場合は削除可）

> ⚠ ADR-032 の「既存ドメイン併用」要件により、`sales-ops-with-claude.firebaseapp.com` は **削除しない**こと（環境変数切り戻し時の保険）。

**追加方法**: 「Add domain」ボタン → ドメイン名を入力 → 「Add」

**削除方法**: 対象ドメイン行の「⋯」または「Delete」アイコン → 確認ダイアログで承認

---

## 3. 作業後の動作確認（必須）

### 3-1. 本番サイトでログインできるか確認

1. シークレットウィンドウで https://jarvis-claude.uk を開く
2. ログイン画面が表示される
3. テストユーザーでログイン試行
4. ログイン成功 → 制限設定OK ✅

### 3-2. 制限が効いているかの確認（できれば実施）

1. Macで別の適当なHTMLファイルを作成（例: `test.html`）:
   ```html
   <!DOCTYPE html>
   <html><body>
   <script type="module">
     import { initializeApp } from "https://www.gstatic.com/firebasejs/10.7.0/firebase-app.js";
     import { getAuth, signInWithEmailAndPassword } from "https://www.gstatic.com/firebasejs/10.7.0/firebase-auth.js";
     const app = initializeApp({
       apiKey: "<YOUR_FIREBASE_WEB_API_KEY>",  // Firebase Console > プロジェクト設定 > 全般 > マイアプリ で確認
       authDomain: "sales-ops-with-claude.firebaseapp.com",
       projectId: "sales-ops-with-claude"
     });
     try {
       await signInWithEmailAndPassword(getAuth(app), "test@example.com", "dummy");
     } catch (e) { document.body.innerText = e.message; }
   </script>
   </body></html>
   ```
2. `file://` でブラウザで開く
3. **「API key not valid」または「Requests from this referrer are blocked」が表示されれば制限OK** ✅
4. 何も表示されない or 認証失敗のみの場合、制限が効いていない可能性 → 設定見直し

### 3-3. 確認後の後始末

- `test.html` を削除
- 本番サイトが正常にログインできることを最終確認

---

## 4. トラブルシューティング

### 症状: 本番サイトでもログインできなくなった

**原因**: Website restrictions の書き方ミス

確認項目:
- `https://jarvis-claude.uk/*` と書いているか（末尾 `/*` 必須）
- `https://www.jarvis-claude.uk/*` が必要な場合は追加
- Cloudflare 経由で `Cloudflare Workers` など使っていないか

**ロールバック**: Application restrictions を一旦「None」に戻す → 原因特定 → 再設定

### 症状: localhost で開発時にエラー

**原因**: `http://localhost:*/*` が未登録

追加方法:
- `http://localhost:5173/*` （Vite デフォルト）
- `http://localhost:*/*` （全ポート許可）

### 症状: 反映されない

**原因**: Google 側の反映待ち（最大5分）

対処: 5分待ってブラウザのキャッシュクリア → 再試行

---

## 5. 完了後に記録すべきこと

作業完了後、`docs/INTERNAL_TEST_RECORD.md` に追記:

```markdown
## セキュリティ設定実施記録
- 実施日: ____/__/__
- 実施者: ____________
- Google Cloud API Key 制限: ☐ 完了
- Firebase 承認済みドメイン: ☐ 完了
- 動作確認: ☐ 本番ログインOK / ☐ 制限効果確認OK
```

---

## 6. 次にやるべきこと

この制限設定が済めば、**Firebase Web API Key が GitHub に公開されていたとしても実害が出ない状態**になります。

内部テスト開始前の準備としては:
1. ✅ 本ガイドの作業完了
2. test-admin パスワード変更（Firebase Console）
3. 内部テスター用アカウントの発行

の順で進めるのがおすすめです。

---

**参考リンク**:
- [Firebase API Keys について（公式）](https://firebase.google.com/docs/projects/api-keys)
- [Google Cloud API Key 制限](https://cloud.google.com/docs/authentication/api-keys#adding_api_restrictions)
- [Firebase 承認済みドメイン](https://firebase.google.com/docs/auth/web/redirect-best-practices)
