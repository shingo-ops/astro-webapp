# ADR-011: Webhook エンドポイント分離（Messenger / Instagram）

- **日付**: 2026-05-01
- **ステータス**: Proposed (Re-review requested — 2026-05-01)
- **決定者**: Shingo（オーナー）
- **起草**: Claude Code (Shingo セッション)
- **レビュー**: Suttan (開発パートナー)

| バージョン | 日付 | 作成者 | 変更内容 |
|---|---|---|---|
| 0.1 | 2026-05-01 | Shingo / Claude Code | 初版起草（調査結果に基づく） |
| 0.2 | 2026-05-01 | Shingo / Claude Code | パートナーレビュー (Suttan) フィードバック反映: Major 1 (object_type 200 OK), Minor 1-10 |

---

## 背景

Phase 1-D Sprint 6 で Instagram 対応を完了した結果、現在 `/api/v1/webhook/messenger` が
Messenger（object=`page`）と Instagram（object=`instagram`）の両オブジェクトを処理している
（`backend/app/routers/webhook.py`、2026-05-01 時点 660 行）。

設計当初は Meta App Review 審査時の Callback URL 一本化を目的として統一エンドポイントを採用した。
しかし以下の理由から、エンドポイント分離が望ましい:

1. **API 設計の不明確さ**: URL 単体から処理対象 platform が判定できない
2. **運用監視の困難**: Messenger と Instagram のログ・メトリクスが混在する
3. **拡張性への制約**: 将来のチャネル追加時に同じパターンを踏めない
4. **Meta App Review の透明性**: 審査担当者が Callback URL から platform 対応を把握できない

---

## 決定内容

### エンドポイント分離

| HTTP メソッド | パス | 認証方式 | 説明 |
|---|---|---|---|
| GET | `/api/v1/webhook/messenger` | Verify Token | Messenger webhook 検証（既存維持） |
| POST | `/api/v1/webhook/messenger` | HMAC-SHA256 | Messenger イベント受信（既存維持） |
| GET | `/api/v1/webhook/instagram` | Verify Token | Instagram webhook 検証（新規追加） |
| POST | `/api/v1/webhook/instagram` | HMAC-SHA256 | Instagram イベント受信（新規追加） |

---

### object_type 検証の方針

各エンドポイントは想定外の object_type を受信した場合、
**200 OK を返しつつ構造化 WARNING ログを出力する**。

#### 理由

1. **Meta の Webhook リトライ仕様**

   Meta は 2XX 以外を返すとリトライする（公式: "If we don't receive a 2XX, we'll retry."）。
   繰り返し非 2XX を返すと Subscription を自動で disable する仕様がある。

   `/messenger` に `object_type=instagram` が来た場合:
   - 400 を返す → Meta がリトライ → 数十回後に Subscription 強制無効化
   - App Review 中にこれが起きると致命的

2. **切替時の伝播ギャップ**

   Meta の Callback URL 変更時に最大 5 分の受信ギャップが発生する。
   この間 `/messenger` に `object_type=instagram` が来た場合、
   400 を返すと IG メッセージを丸ごとロストする。

#### 実装

```python
from typing import Literal

async def _handle_meta_webhook(request, db, *, platform: Literal["messenger", "instagram"]):
    body = await request.json()
    object_type = body.get("object")

    expected = "page" if platform == "messenger" else "instagram"
    if object_type != expected:
        logger.warning(
            "[Meta] mismatched_object_type",
            extra={
                "endpoint_platform": platform,
                "received_object_type": object_type,
                "entry_count": len(body.get("entry", []) or []),
            },
        )
        return Response(status_code=200)  # Meta にリトライさせない
    # ... 処理続行
```

#### 運用

- `mismatched_object_type` ログを Datadog/Sentry でアラート化（一定数超で通知）
- Meta 設定変更の伝播状況をアプリログで監視可能

---

### 内部実装方針

```python
from typing import Literal

WebhookPlatform = Literal["messenger", "instagram"]
```

共通ハンドラ `_handle_meta_webhook(request, db, *, platform: Literal["messenger", "instagram"])`
を `webhook.py` に追加し、各エンドポイントから呼び出す。

HMAC 検証には生 body bytes と `X-Hub-Signature-256` ヘッダの両方が必要なため、
`request` オブジェクト全体を渡す設計とする。

### 共通ハンドラの責務

`_handle_meta_webhook(request, db, *, platform: Literal["messenger", "instagram"])` は以下を担当する:

1. HMAC-SHA256 署名検証（`X-Hub-Signature-256`、既存コード再利用）
2. `object_type` 検証（上記の 200 OK + WARNING 方針に従う）
3. `entry` ループ + テナント解決（`_get_tenant_id_by_page` / `_get_tenant_id_by_ig_account`）
4. `_iter_inbound_messages`: 現状の object_type 自動判別をそのまま活かす
   （platform 引数追加は冗長になるため、既存実装 `webhook.py` の実装を維持）
5. `_persist_meta_message` 呼び出し（`platform` 引数を渡す）
6. Discord 通知: 現状の同期実行を維持
   （`send_discord_notification` を `_persist_meta_message` 後にループ内で同期呼出）
   非同期化は Risk 4 の通り ADR-012 のスコープで扱う。

---

### GET エンドポイント（hub.challenge）の扱い

両エンドポイント（`/messenger`、`/instagram`）で同一の `META_VERIFY_TOKEN` を共有する。
実装は既存の `verify_messenger_webhook` ロジックを `verify_instagram_webhook` にも流用する。

両方とも同じ `META_VERIFY_TOKEN` を共有（シンプルさ優先）。

**将来の移行パス:** テナントごとに verify_token を分離する要件が出た場合、
テナント別 verify_token は別途 ADR-XXX で検討する。

---

### Meta App Dashboard 設定変更（Shingo 手動）

Phase 4 で以下を変更する:

| object | 変更前 Callback URL | 変更後 Callback URL |
|---|---|---|
| page | `https://api.salesanchor.jp/api/v1/webhook/messenger` | 変更なし |
| instagram | `https://api.salesanchor.jp/api/v1/webhook/messenger` | `https://api.salesanchor.jp/api/v1/webhook/instagram` |

Verify Token はどちらも `META_VERIFY_TOKEN` 環境変数を共有。

---

## 実装計画

### Phase 1: 検証（実装前・Shingo 担当）

**Step 1:** 現在の `/webhook/messenger` で Instagram Webhook を受信できることを確認する。

**Step 2:** `/webhook/messenger` へのテスト送信（手動 curl / Meta Dashboard テスト送信）

**合格基準:**
- ログに `POST /api/v1/webhook/messenger 200` が記録される
- `meta_messages` テーブルに `platform='instagram'` の行が INSERT される
- Discord 通知が到達する
- **上記 3 点いずれか不達の場合、Phase 3（実装）には進まない**

---

### Phase 2: 設計レビュー（パートナー確認）

本 ADR のレビューを Suttan に依頼し、Accepted を確認してから Phase 3 着手。

---

### Phase 3: 実装（Claude Code 担当、1〜1.5日）

#### Day 1（4〜4.5 時間）

| タスク | 見積 | 内容 |
|---|---|---|
| 共通ヘルパー抽出 | 30分 | `_handle_meta_webhook(request, db, *, platform: Literal[...])` を `webhook.py` に追加。Literal 型導入、object_type 200 OK + WARNING ロジック |
| POST 2 endpoint 分離 | 30分 | POST `/webhook/instagram` を追加、platform 引数を渡す形に変更 |
| GET hub.challenge 分離 | 30分 | GET `/webhook/instagram` を追加（`verify_messenger_webhook` と同ロジック） |
| 既存テスト 対応 | 1.5〜2時間 | fixture 外出し + contract test + caplog 対応 + デバッグ |
| IG 専用 E2E | 1時間 | `/webhook/instagram` への E2E テスト追加 |

**Day 1 合計: 4〜4.5 時間**

#### Day 2（6〜7 時間）

| タスク | 見積 |
|---|---|
| ADR Accepted 更新 | 5分 |
| 影響ドキュメント 4ファイル更新 | 90分 |
| Meta 提出資料 docx 更新 | 1時間 |
| PR レビュー & Reviewer 対応 | 2〜3時間 |
| develop → main マージ | 30分 |
| Meta App Dashboard 設定変更 | 15分 |
| 本番動作確認 | 1時間 |

**Day 2 合計: 6〜7 時間**

**総工数: 10〜11.5 時間（1〜1.5日）**

---

### Phase 4: 本番反映

1. develop → main PR → merge
2. VPS 自動デプロイ（CI/CD 経由）
3. Meta App Dashboard で instagram object の Callback URL を変更
4. 動作確認（実 IG DM 送信）

---

## テスト戦略

### 既存テスト対応

既存 `backend/tests/test_webhook_instagram.py` のテストはパラメータ化済みのため、
`process_messenger_event` → `_handle_meta_webhook(request, db, *, platform=...)` への
リファクタリングで既存テストの大半が対応可能。

fixture の外出しと caplog を使ったログ検証を追加する。

### 新規テストケース

| テストケース名 | 内容 |
|---|---|
| `test_instagram_endpoint_get_returns_challenge` | GET `/webhook/instagram` でチャレンジ返却 |
| `test_instagram_endpoint_post_accepts_instagram_object` | POST `/webhook/instagram` で `object=instagram` を正常処理 |
| `test_mismatched_object_type_returns_200_and_logs_warning` | 誤った object_type でも 200 を返す（Meta リトライ抑止）。WARNING ログを確認 |
| `test_messenger_endpoint_rejects_invalid_signature` | HMAC 不一致で 403 |

```python
@pytest.mark.parametrize("path,wrong_object_type", [
    ("/api/v1/webhook/messenger", "instagram"),
    ("/api/v1/webhook/instagram", "page"),
])
async def test_mismatched_object_type_returns_200_and_logs_warning(
    path, wrong_object_type, caplog
):
    """誤った object_type でも 200 を返す（Meta リトライ抑止）。WARNING ログを確認。"""
    # ... (HMAC 付き POST)
    assert response.status_code == 200
    assert any("mismatched_object_type" in r.message for r in caplog.records)
```

---

## ロールバック計画

### トリガー

以下のいずれかが発生した場合、ロールバックを実行する:

- 本番デプロイ後、Instagram Webhook が受信されない
- Messenger Webhook が受信されない（回帰）
- Meta Subscription が auto-disabled された
- エラーレートが 5% を超える

### 手順

1. Meta App Dashboard で instagram object の Callback URL を `/webhook/messenger` に戻す
2. コード revert（`git revert`）+ 再デプロイ（任意）

### RTO

| フェーズ | 目標時間 |
|---|---|
| 即時対応（Meta Dashboard URL revert + 伝播完了） | 10〜15分以内 |
| 完全 rollback（コード revert + 再デプロイ） | 目標 30分、最大 45分 |
| nginx 503 設定（オプション、必要時のみ） | 追加で 15分 |

**RTO 根拠:**

```
Meta App Dashboard 操作 + 2FA:    1〜2分
Subscription URL 編集・保存:       1分
Meta 側の伝播待ち:                最大 5分
動作確認 (テスト送信):             2分
合計:                              9〜10分 → 10〜15分が現実的
```

---

## 影響と注意事項

### 影響ドキュメント

| ファイル | 対応内容 |
|---|---|
| `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md` | instagram object Callback URL を `/webhook/instagram` に更新 |
| `docs/PHASE_1D_META_INBOX_OVERVIEW.md` | エンドポイント一覧に `/webhook/instagram` を追記 |
| `docs/PHASE5_DOMAIN_CUTOVER_RUNBOOK.md` | `/webhook/instagram` も cutover 対象に追加 |
| `docs/PHASE_1D_RELEASE_NOTES.md` | Sprint 7 として記録 |

### Risks

#### Risk 1: Meta Subscription auto-disable

Meta App Dashboard で instagram の Callback URL 変更中、旧 URL への Webhook が断続的に来た場合。

**緩和:** Callback URL 変更作業を 5 分以内で完了し、動作確認テストを即実施する。
object_type 検証を 200 OK にすることで、伝播ギャップ中も Subscription が無効化されない。

#### Risk 2: 切替中の IG メッセージロスト

Callback URL 変更の伝播中（最大 5 分）に `/messenger` へ `object_type=instagram` が来た場合。

**緩和:** object_type 検証を 200 OK + WARNING にすることで、伝播ギャップ中も
IG メッセージをロストしない（Messenger エンドポイントが受け取って正常処理する）。

#### Risk 3: テスト fixture 変更によるデグレ

既存テストのリファクタリング中に fixture 変更でデグレが発生する可能性。

**緩和:** Day 1 終了時点で CI 全テストグリーンを確認してから Day 2 着手。

#### Risk 4: Discord 通知の同期実行による Meta Webhook 遅延

**懸念:** 現状 `send_discord_notification` は `_persist_meta_message` の直後に
同期で呼ばれる（`webhook.py` 行 642 付近）。Discord rate limit（50req/sec/bot）に
当たった場合、Meta Webhook 全体が遅延し、Meta 側で timeout（10s）する可能性がある。

**緩和策:**
- Phase 3 では現状維持（同期実行）
- 非同期化は ADR-012（Discord Bot Architecture）のスコープで扱う
- 監視: Meta Webhook の応答時間メトリクスを Datadog で観測

---

## 代替案

| 案 | 評価 |
|---|---|
| **統一 endpoint のまま維持** | ❌ 却下。URL から platform が判定できず、監視・拡張性に欠ける |
| **query param で platform 指定（`/webhook?platform=messenger`）** | △ 非標準 API 設計。Meta App Review で precedent なし |
| **endpoint 分離（本決定）** | ✅ 採用。API 設計が明確、拡張性が高い |

---

## Operational Notes (Manual Operations Log)

| 日時 | 操作 | 担当 | 理由 |
|---|---|---|---|
| （本番リリース時に記録） | Meta Dashboard instagram Callback URL 変更 | Shingo | 本 ADR Phase 4 に従い |

---

## 関連

- ADR-010: main ブランチ保護 Ruleset 導入（`docs/decisions/ADR-010-branch-protection.md`）
- ADR-009: Discord 連携 Bot 常駐アーキテクチャ（Discord 通知非同期化は ADR-012 スコープ）
- 実装対象: `backend/app/routers/webhook.py`（2026-05-01 時点 660 行）
- テスト対象: `backend/tests/test_webhook_instagram.py`
- 影響 spec: `docs/PHASE_1D_META_INBOX_OVERVIEW.md` §4-5
- 影響 checklist: `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md` A-3
- 影響 runbook: `docs/PHASE5_DOMAIN_CUTOVER_RUNBOOK.md`

### Communication Logs

| 日時 | 内容 |
|---|---|
| 2026-05-01 00:00 | ADR-011 初版起草（Shingo / Claude Code セッション、調査結果に基づく） |
| 2026-05-01 1:43 | パートナーから「YES, 賛成。ただし4条件あり」回答 |
