# ADR-023: スタッフライフサイクル操作における認証3層の同期化

## ステータス

提案 — Meta App Review 通過後に着手

## コンテキスト

Sales Anchor の認証は以下の3層構造で成立している：

1. **Firebase Authentication**（認証情報・MFA）
2. **`public.users`**（テナント横断のグローバルユーザー台帳）
3. **`tenant_XXX.staff`**（テナント内の業務情報、役職、スタッフコード等）

ログイン処理 (`backend/app/auth/dependencies.py`) は `public.users` を email で検索する設計のため、`public.users` にレコードが存在しないユーザーはログイン時に 401「ユーザーが見つかりません」で拒否される。

**現状、3層を一気通貫で作成・削除する正規エンドポイントが存在しない**：

| 既存エンドポイント | Firebase Auth | public.users | tenant_XXX.staff |
|---|---|---|---|
| `POST /auth/register` | ❌ フロント側で別途 | ✅ INSERT | ❌ |
| `POST /staff` (UI からのスタッフ追加) | ❌ | ❌ | ✅ INSERT |
| `DELETE /staff/{id}` | ❌ | ❌ | ✅ DELETE |
| `PATCH /staff/{id}` (status変更) | ❌ | ❌ | ✅ UPDATE |

結果として、**Sales Anchor の管理画面からスタッフ追加機能で追加された全ユーザーが、ログイン時に 401 エラーで拒否される構造的バグ**が存在する。

このバグは 2026-05-11 の Meta App Review 用テストアカウント (`review@salesanchor.jp`) のログイン障害調査により発見された。

## 決定（What）

スタッフのライフサイクル操作（追加・削除・status変更）を、Firebase Auth・`public.users`・`tenant_XXX.staff` の3層すべてで整合性を保って実行する正規エンドポイントを確立する。

- **スタッフ追加**: 3層すべてに作成
- **スタッフ削除**: 3層すべてから削除（または論理削除で同期）
- **スタッフ status 変更**（active ↔ inactive）: `public.users.is_active` も同期

## なぜ（Why）

- 現状の管理画面スタッフ追加機能が機能不全（追加した新規スタッフがログイン不能）
- 認証データモデルの整合性をバックエンド側で保証する責務がある（フロント・運用に分散させない）
- 新規顧客テナント受け入れ前に必須の修正（新規顧客はスタッフ追加機能を必ず使う）
- Meta App Review 用に手動対応した `review@salesanchor.jp` のような暫定対応を恒久化したくない

## スコープ外

- `backend/app/auth/dependencies.py` の変更
  - 同ファイルは `DEVELOPMENT_GUIDE_FOR_SHINGO.md` で「変更禁止: 認証・認可の中核」と明記されているため触らない
  - 「`public.users` で検索する」という設計判断はそのまま維持し、書き込み側で整合性を担保する
- `POST /auth/register` エンドポイントの再設計・廃止判断
  - 別ADRで扱う
- 既存スタッフユーザー（Shingo、review@salesanchor.jp）への遡及対応
  - すでに3層に登録済みのため、本ADRのスコープでは触らない
- Firebase Auth のパスワードリセット・MFA再設定フローの実装
  - 別途検討
- スタッフ招待メール送信機能
  - 別途検討

## 事業上の制約

- **Meta App Review 申請の妨げにならないこと**: 申請通過（および撮影完了）後に着手する
- **既存 HIGH LIFE JPN テナント（tenant_004）への破壊的変更なし**: 既存スタッフの動作継続を保証
- **新規顧客テナント受け入れ開始前に完了必須**: 営業活動の前提条件
- **仮パスワードの安全な配布手段が必要**: 管理者画面に表示、招待メール、または管理者が手動配布のいずれか（実装判断はパートナーに委ねる）
- **MFA_REQUIRED=true 環境での運用を前提**: 新規スタッフが初回ログイン後に MFA を設定するフローと矛盾しないこと

## 関連

- 発見経緯: 2026-05-11 `review@salesanchor.jp` ログインエラー調査
- 関連実装ファイル（実装判断はパートナーに委ねる、参考情報）:
  - `backend/app/auth/dependencies.py`（変更禁止、参照のみ）
  - `backend/app/routers/staff.py`（create_staff / delete_staff / update_staff）
  - `backend/app/routers/auth.py`（register_user の挙動と整合確認）
  - `backend/app/models.py`（User モデル定義）
- 関連ADR: ADR-012（What/How 役割分担モデル）
