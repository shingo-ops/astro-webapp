# ADR-021: Meta App Review 撮影用テナント分離

| 項目 | 内容 |
|------|------|
| ステータス | Proposed |
| 作成日 | 2026-05-14 |
| 関連 | ADR-012, ADR-019, ADR-025 |

## What

Meta App Review 撮影および審査プロセス専用の Sales Anchor テナントを新規作成し、Shingo の業務テナントから完全に分離する。

- 新テナント名: `tenant_review`（命名はパートナー判断）
- 所属ユーザー: `review@salesanchor.jp` を新テナントに紐付け
- データ: Demo Customer × 7 のみ、実顧客データは一切含まない
- Meta 連携: OAuth 再接続で新テナントに紐付ける（HIGH LIFE JPN Test Page + treasureislandjapan）

## Why

### レビュアー実アクセスへの対応

Meta 公式ガイドライン「Make sure we can access your app or website」より、レビュアーは申請されたアプリへの実アクセス権を持つ。特に Messenger / Instagram メッセージング機能の検証では、レビュアーが自身でテストメッセージを送信し、Sales Anchor 内での受信・返信動作を確認する可能性が高い。

### データ漏洩リスクの完全排除

現状の `review@salesanchor.jp` は Shingo の業務テナントに所属しており、Dashboard / Customers / Recent customers 画面に実顧客（52 件）が表示される。撮影での編集カットやモザイク処理では以下のリスクが残る:

- 動画のコマ送り再生で実顧客名が一瞬露出
- レビュアー実アクセス時の全画面露出
- モザイク処理が「何かを隠している」と審査での疑念を生む

業界標準（SaaS デモコンテンツガイドライン）では、レビュー用環境は本番から完全に分離されることが推奨される。

### 法的リスクの回避

実顧客データの動画露出は以下に抵触するリスクがある:
- GDPR（EU 圏顧客が含まれる場合）
- 日本の個人情報保護法
- B2B 取引における守秘義務

## Scope 外

- 既存業務テナントのデータ削除・変更（一切手を付けない）
- 撮影完了後の `tenant_review` の取り扱い（撮影後に Shingo が判断）
- マルチテナント機能の新規実装（既存機能の利用のみ）
- 新テナントでの独自機能開発
- Facebook / Instagram のテストアカウント新規作成（既存の Shingo Facebook + Samuraisoul Katana テスター + HIGH LIFE JPN Test Page + treasureislandjapan をそのまま利用）

## 事業上の制約

### 撮影スケジュール

新テナント作成および OAuth 再接続で 1.5〜2 時間程度の遅延が発生する。許容範囲内。

### Meta 連携の重複

`HIGH LIFE JPN Test Page` と `treasureislandjapan` を新テナントに紐付ける際、既存業務テナントとの紐付けが解除される可能性がある。事前確認が必要。

万が一既存業務テナントの Meta 連携が解除された場合、撮影完了後に既存テナント側で OAuth 再接続を行う必要がある。

### ADR-019 への影響

ADR-019（テストデータ作成方針）は新テナント `tenant_review` で実施する形に修正する。既存業務テナント `tenant_004` には Demo Customer を作成しない。

### ADR-025 への配慮

新テナント作成は通常の管理者操作であり、ADR-025 の禁止対象（OAuth フロー外での tenant_meta_config 等への直接 INSERT/UPDATE）には該当しない。新テナントの Meta 連携は OAuth 再接続で正規に行う。

### Facebook / Instagram 側のデータ露出について

`HIGH LIFE JPN Test Page` と `treasureislandjapan` には Shingo の実顧客とのやり取り履歴が残っているが、Sales Anchor の審査スコープ外であり、撮影で Facebook Page Inbox / Instagram Direct を映さなければ問題ない。撮影台本に「撮影禁止事項」を別途明記する。

## 受け入れ基準

1. `tenant_review` が作成され、`review@salesanchor.jp` でログインできる
2. Dashboard / Customers / Recent customers にデータが「0 件」または「Demo データのみ」表示される
3. 既存業務テナント（tenant_004 等）のデータは一切変更されていない
4. Meta 連携が新テナントで動作する（Messenger / Instagram 受信・返信すべて成功）
5. Bug #1（Messenger 名前更新）と ADR-018（Instagram Send endpoint 修正）の動作が新テナントで確認できる
