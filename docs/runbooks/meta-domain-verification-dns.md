# Meta ドメイン認証 — さくらインターネット DNS TXT レコード追加 Runbook

| 項目 | 値 |
|---|---|
| 起票日 | 2026-05-08 |
| 根拠 ADR | [ADR-018](../adr/ADR-018.md) |
| 担当 | しんごさん（さくらインターネット コンパネ操作） |
| 検証担当 | Hikky-dev（DNS 伝搬確認） |

---

## 0. 背景

Meta Business Verification のドメインオーナーシップ証明を、HTML メタタグ方式（[ADR-016](../adr/ADR-016.md)）から DNS TXT レコード方式（[ADR-018](../adr/ADR-018.md)）に切り替える。

メタタグ方式では Meta のクローラーが `salesanchor.jp` のフロントエンド HTML 取得時に 403 を返し続けた経緯がある（[ADR-017](../adr/ADR-017.md) で robots.txt に `facebookexternalhit` を Allow しても解消せず）。DNS 方式は HTTP 層に依存しないため、この事象の影響を受けない。

---

## 1. 追加する DNS レコード

| 項目 | 値 |
|---|---|
| ゾーン | `salesanchor.jp` |
| Type | `TXT` |
| Host / 名前 | `@`（ルートドメイン。さくらコンパネ上は空欄または `@`） |
| Value / 値 | `facebook-domain-verification=r38od7qknawjulwqpmvbpso1q1zfy4` |
| TTL | 既定値で可（さくら標準 = 3600 秒） |

**注意**:
- 値はダブルクォートで囲む必要なし（さくらのフォームは自動でクォートを付与する）。
- 既存の TXT レコード（SPF, DKIM, DMARC 等）を**変更・削除しない**。新規追加のみ。

---

## 2. 追加手順（しんごさん作業）

### 2-1. さくらインターネット コンパネにログイン
- https://secure.sakura.ad.jp/
- 「ドメイン / SSL」→「salesanchor.jp」→「ゾーン編集」

### 2-2. レコード追加
1. 「変更」→「新しいエントリー追加」
2. エントリ名: `@`（または空欄、ルート指定）
3. タイプ: `TXT`
4. 値: `facebook-domain-verification=r38od7qknawjulwqpmvbpso1q1zfy4`
5. 「新規追加」→「データ送信」で確定

### 2-3. 確定の確認
- ゾーン編集画面のレコード一覧に追加した TXT レコードが表示されることを確認。
- 既存の TXT レコード（SPF 等）が消えていないことを併せて確認。

---

## 3. 検証手順（Hikky-dev / しんごさん）

### 3-1. DNS 伝搬確認

ローカルマシンから:

```
dig +short TXT salesanchor.jp
```

期待される出力（既存レコードに加えて以下の 1 行が含まれる）:

```
"facebook-domain-verification=r38od7qknawjulwqpmvbpso1q1zfy4"
```

複数の DNS リゾルバで確認する場合:

```
dig +short TXT salesanchor.jp @8.8.8.8
dig +short TXT salesanchor.jp @1.1.1.1
```

伝搬には最大 TTL 分（既定 3600 秒 = 1 時間）かかる。さくら自身の DNS（`ns1.dns.ne.jp` 等）には数分以内に反映される。

### 3-2. Meta Business Suite 側の認証実行

1. Meta Business Suite → 「ビジネス設定」→「ブランドセーフティ」→「ドメイン」
2. `salesanchor.jp` を選択 → 「ドメインを認証」
3. 認証方式 = **DNS TXT レコード** を選択
4. 「ドメインを認証」ボタン押下
5. 「認証済み」表示に変わることを確認

伝搬未完了で失敗した場合は 5〜30 分待って再試行。

---

## 4. ロールバック

DNS 設定の不具合により他サービス（メール送信等）に影響が出た場合のみ:

1. さくらコンパネ → ゾーン編集
2. 追加した `facebook-domain-verification=...` の TXT レコードを削除
3. 「データ送信」で確定

メタタグ方式（ADR-016）への戻しは別作業。

---

## 5. 完了条件

- [ ] さくら DNS に TXT レコードが追加されている
- [ ] `dig +short TXT salesanchor.jp` の出力に `facebook-domain-verification=r38od7qknawjulwqpmvbpso1q1zfy4` が含まれる
- [ ] Meta Business Suite 上で `salesanchor.jp` が「認証済み」と表示される
- [ ] 既存 TXT レコード（SPF / DKIM / DMARC 等）が破壊されていない

---

## 参考

- [ADR-016: Facebook ドメイン認証メタタグの追加](../adr/ADR-016.md)
- [ADR-017: robots.txt facebookexternalhit Allow 化](../adr/ADR-017.md)
- [ADR-018: salesanchor.jp DNS TXTレコードによるMetaドメイン認証](../adr/ADR-018.md)
- Meta 公式ドキュメント: https://www.facebook.com/business/help/406146856965302
