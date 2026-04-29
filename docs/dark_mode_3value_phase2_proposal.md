# dark_mode 3値化（light/dark/auto）— Phase 2 投入提案

| 項目 | 内容 |
|------|------|
| ステータス | **Deferred to Phase 2**（2026-04-29 しんごさん判断） |
| 起草日 | 2026-04-29 |
| 起案理由 | 現状 boolean 2値だが CSS は既に 3-state 対応。OS テーマと一貫性が取れない UX 課題 |
| 投入タイミング | Phase 2（販売・財務拡張）と同時、または UI/UX 改善まとめ PR として |
| 推定工数 | 1.5 日（実装 0.5 + Reviewer 0.5 + VPS 0.5） |

---

## 0. TL;DR

- **問題**: 現状 `staff_ui_preferences.dark_mode` は boolean（true/false 固定）。「OS 設定に従う」auto モードが選べない
- **CSS は既に対応済**: `index.css:52-58` で `force-dark` / `force-light` / 何も無し（=auto）の 3-state を実装済
- **本提案**: DB を VARCHAR に変更（または新規列追加）し、ユーザーが auto を明示選択可能にする
- **後回し理由**: 現状の boolean 運用に致命的問題なし、機能追加（B-2 M3 / B-3 M3/M4）の優先度が高い

## 1. 現状の挙動

### CSS レイヤー（index.css）
```
html.force-dark        → 強制ダーク
html.force-light       → 強制ライト
class なし             → OS の prefers-color-scheme に従う（= auto 相当）
```

### Frontend UiPrefsContext の class 適用
```
prefsFetched=false（fetch 中）  → どちらも付けない（auto 状態）
prefsFetched=true, dark_mode=true  → force-dark
prefsFetched=true, dark_mode=false → force-light
```

### 結論
- auto 状態は「fetch 過渡期の数百 ms」だけ存在
- 永続的に auto を選べる UI/DB 設計が無い

## 2. ユースケース

| ユーザー | 課題 |
|---|---|
| OS テーマを朝/夜自動切替している人 | アプリ内設定をどちらかに固定すると OS と乖離 |
| iOS/macOS の Auto モードユーザー | force-light/force-dark 一択でアプリが OS の自動切替に追従しない |
| プレゼン/外光で頻繁切替したい人 | 都度メニューから手動 toggle 必要 |

## 3. 提案設計

### 案 A-1: 既存 boolean を VARCHAR に置換（**推奨**）

```sql
-- migration NNN_change_dark_mode_to_theme_mode.sql
ALTER TABLE {schema}.staff_ui_preferences
  ALTER COLUMN dark_mode TYPE VARCHAR(10)
  USING (CASE WHEN dark_mode THEN 'dark' ELSE 'auto' END);

ALTER TABLE {schema}.staff_ui_preferences
  ADD CONSTRAINT staff_ui_preferences_dark_mode_check
  CHECK (dark_mode IN ('light', 'dark', 'auto'));

ALTER TABLE {schema}.staff_ui_preferences
  ALTER COLUMN dark_mode SET DEFAULT 'auto';

-- 列名 'dark_mode' を 'theme_mode' に rename したいなら追加で:
ALTER TABLE {schema}.staff_ui_preferences
  RENAME COLUMN dark_mode TO theme_mode;
```

**メリット**: 列が増えない、ロジックがシンプル
**デメリット**: 破壊的（rollback 時に値が 1 つに集約される）

### 案 A-2: 新規列追加（後方互換）

`theme_mode VARCHAR(10) NOT NULL DEFAULT 'auto'` を新設、`dark_mode` は deprecated として残す。後の Phase で削除。

**メリット**: API ロールアウトが安全（並行稼働期間あり）
**デメリット**: 一時的に冗長な列

## 4. 実装影響範囲

| ファイル | 変更行数（推定）|
|---|---|
| `migrations/NNN_change_dark_mode_to_theme_mode.sql`（新規）| 30 |
| `backend/app/services/tenant.py`（template 同期）| 2 |
| `backend/app/schemas/staff.py` | 5 |
| `backend/app/routers/staff.py` | 10 |
| `backend/tests/conftest.py`（test schema 同期）| 2 |
| `backend/tests/test_staff_me.py`（assertion 更新）| 5 |
| `frontend/src/contexts/UiPrefsContext.tsx` | 30 |
| `frontend/src/pages/StaffPage.tsx`（フォーム UI 改修）| 20 |
| `frontend/src/components/Layout.tsx`（参照箇所）| 5 |
| `.github/workflows/deploy.yml`（migration NNN 追加）| 5 |
| **合計** | **~115 行** |

## 5. UI 案

### 現状
```
☑ ダークモード  （チェックボックス 1 個）
```

### 提案
```
テーマ:
  ○ 🌓 自動（OS 設定に従う）  ← default
  ○ ☀️ ライト
  ○ 🌙 ダーク
```

## 6. トレードオフ

### メリット
- ✅ OS テーマと一貫性
- ✅ ユーザーが auto を明示選択可能
- ✅ CSS は既に対応済（実装コスト低）

### デメリット
- ⚠️ 既存 `dark_mode` boolean を参照するコードを全て書き換え（grep 漏れリスク）
- ⚠️ migration が破壊的（rollback 時に値集約）
- ⚠️ Phase 1 安定運用中の UX 改修は優先度低

## 7. 投入タイミング案

| 候補 | 理由 |
|---|---|
| **Phase 2 と同時** ⭐ | UI/UX 改修まとめで Reviewer 負担を集約、テスト工数も束ねられる |
| 単独 PR（次セッション） | 工数 1.5 日、本提案承認後すぐ着手可 |
| 永久保留 | 現状で実害がほぼない、要望あれば再評価 |

## 8. 関連ファイル（実装時の参考）

- `frontend/src/index.css:52-65` — CSS 3-state 対応済の証拠
- `frontend/src/contexts/UiPrefsContext.tsx:131-146` — class 適用 useEffect
- `backend/app/schemas/staff.py:30` — Pydantic `dark_mode: bool = False`
- `backend/app/services/tenant.py:663` — DB schema `dark_mode BOOLEAN NOT NULL DEFAULT FALSE`
- `migrations/019_create_staff_tables.sql:97` — 元の DB 定義

## 9. メモ

- 本提案は 2026-04-28 セッションで起案、しんごさん判断で **Phase 2 投入** に決定（2026-04-29）
- Phase 2 着手時に本書を起点に migration + 実装に入る
- それまで現状の boolean 運用を維持
