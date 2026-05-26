# test-admin パスワード変更手順（SSH直接実行版）

**目的**: `test-admin@jarvis-test.local` のパスワードを Firebase Admin SDK で直接変更する
**実施者**: しんごさん or hitoshiさん（Mac側ターミナル）
**所要時間**: 約10分
**重要**: 新パスワード文字列は **Claude Code (このチャット) には絶対に貼り付けない**

---

## 0. 事前準備

### Mac側で新パスワードを生成

ターミナルで実行（**Mac側**）:

```bash
LC_ALL=C tr -dc 'A-Za-z0-9!@#$%^&*()_+=-' < /dev/urandom | head -c 24 && echo
```

→ 出力された24文字をパスワードマネージャ等に保管。**Claude Code のチャット欄には貼らない**。

---

## 1. VPSへSSH

**Mac側**で実行:

```bash
ssh ubuntu@49.212.137.46
```

以降のコマンドはすべて **VPS側** で実行します。

---

## 2. スクリプトを作成

**VPS側**で実行（パスワード値はまだ入れない）:

```bash
cat > /tmp/change_password.py <<'PYEOF'
import sys
import firebase_admin
from firebase_admin import auth, credentials

if len(sys.argv) != 3:
    print("Usage: python change_password.py <uid> <new_password>")
    sys.exit(1)

uid = sys.argv[1]
new_password = sys.argv[2]

cred = credentials.Certificate('/app/firebase-credentials.json')
firebase_admin.initialize_app(cred)

auth.update_user(uid, password=new_password)
print(f"Password updated successfully for UID: {uid}")
PYEOF
```

```bash
# backendコンテナにスクリプトをコピー
docker cp /tmp/change_password.py astro-webapp-backend-1:/tmp/change_password.py
```

---

## 3. パスワードを実際に変更

**VPS側**で実行（`<<ここに新パスワード>>` 部分を実際の値に置換、シングルクォートで囲む）:

```bash
docker exec astro-webapp-backend-1 python /tmp/change_password.py \
  NJiwFSFTlOQgt9AOKxNIRLPmNe42 \
  '<<ここに新パスワード>>'
```

### 成功時の出力

```
Password updated successfully for UID: NJiwFSFTlOQgt9AOKxNIRLPmNe42
```

### 失敗時の対処

| エラー | 原因 | 対処 |
|--------|------|------|
| `ModuleNotFoundError: firebase_admin` | コンテナにSDK未インストール | `docker exec astro-webapp-backend-1 pip list \| grep firebase` で確認 |
| `Permission denied: firebase-credentials.json` | 認証ファイル権限 | `docker exec astro-webapp-backend-1 ls -la /app/firebase-credentials.json` |
| `auth/weak-password` | パスワード短すぎ | 8文字以上、推測されにくい文字列に |
| `auth/user-not-found` | UID間違い | UID を再確認 |

---

## 4. 動作確認

ブラウザで https://jarvis-claude.uk を開いてログイン:

- メアド: `test-admin@jarvis-test.local`
- パスワード: 新しく設定したもの

ログイン成功すれば変更完了 ✅

---

## 5. クリーンアップ（必須）

スクリプトには平文パスワードが含まれていないが、念のためコンテナ内とVPS上の両方から削除:

```bash
# VPS側で実行
docker exec astro-webapp-backend-1 rm /tmp/change_password.py
rm /tmp/change_password.py
```

bash 履歴にパスワードが残っているので消去:

```bash
# VPS側で実行
history -c && history -w
```

**Mac側のターミナル**でも履歴消去:

```bash
# Mac側で実行
history -c
```

`.zsh_history` / `.bash_history` のファイルも念のため確認:

```bash
# Mac側で実行
grep -c 'change_password' ~/.zsh_history 2>/dev/null
# 0 でなければ手動で該当行を削除
```

---

## 6. SSH切断

```bash
# VPS側で実行
exit
```

---

## 7. 完了報告

完了したら Claude Code に「**test-admin パスワード変更完了**」とだけ伝えてください。
（**新パスワードの値は伝えないこと**）

完了報告を受けたら、私が以下を実施します:
- メモリファイル `project_stage5_progress.md` の旧パスワード記載削除
- `INTERNAL_TEST_RECORD.md` への実施記録追記
- 次のタスク（内部テスター登録）への移行

---

## 補足: 新パスワードの保管場所

| 推奨度 | 保管場所 |
|--------|---------|
| 🥇 | パスワードマネージャ（1Password 等）または GitHub Secrets |
| 🥈 | Mac の Keychain |
| 🥉 | 紙にメモして金庫 |
| ❌ | テキストファイル平文、メール、Slack、Claude Code |
