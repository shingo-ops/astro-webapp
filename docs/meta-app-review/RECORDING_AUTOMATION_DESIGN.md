# Meta App Review 撮影自動化 — 設計書（Whisper 統合版）

| 項目 | 内容 |
|------|------|
| 作成日 | 2026-05-15 |
| ステータス | 実装中 |

---

## 全体フロー（4フェーズ）

```
Phase 1: 音声生成（完了）
  ElevenLabs Adam で scene1〜8.mp3 生成
  保存先: ~/Desktop/salesanchor_audio_liam/
        ↓
Phase 2: Whisper 文字起こし（タイムスタンプ取得）
  local-whisper-ollama で全シーンを英語で文字起こし
  → 各操作キーワードの正確な秒数を特定
        ↓
Phase 3: タイムスタンプを Playwright スクリプトに組み込む
  wait(ハードコード秒数) → wait(Whisper で特定した正確な秒数)
        ↓
Phase 4: 撮影実行
  QuickTime 録画開始 → Playwright スクリプト実行
  → 手動操作ポイントのみ Shingo が操作
  → QuickTime 録画停止
```

---

## 技術スタック

| コンポーネント | 役割 | 場所 |
|-------------|------|------|
| ElevenLabs API（Adam）| ナレーション音声生成 | ~/Desktop/salesanchor_audio_liam/ |
| **local-whisper-ollama** | 音声→タイムスタンプ付き文字起こし | ~/sales-ops-with-claude/02_apps/whisper-tts-tool/local-whisper-ollama |
| Playwright | Chrome 自動操作（headless: false）| ~/Desktop/salesanchor_recording.py |
| afplay | MP3 再生（macOS 内蔵）| 追加インストール不要 |
| QuickTime Player | 画面収録（1920x1080）| macOS 内蔵 |

---

## Phase 2: Whisper 文字起こし手順

### 実行コマンド

```bash
cd ~/sales-ops-with-claude/02_apps/whisper-tts-tool/local-whisper-ollama
source venv/bin/activate

# 全シーンを英語で文字起こし（タイムスタンプ付き）
for i in 1 2 3 4 5 6 7 8; do
  echo "=== Scene $i ==="
  python main.py ~/Desktop/salesanchor_audio_liam/scene${i}.mp3 -l en
done
```

### 出力フォーマット（例: scene1）

```
[00:00:00.000 - 00:00:03.200] Welcome to Sales Anchor, a B2B SaaS CRM platform
[00:00:03.200 - 00:00:08.500] Sales reps manage leads, deals, and customer conversations
[00:00:08.500 - 00:00:15.100] In this video, we will demonstrate how Sales Anchor integrates
[00:00:15.100 - 00:00:22.300] Facebook Messenger and Instagram Direct Messages into the CRM inbox
[00:00:22.300 - 00:00:33.000] Sales reps can reply to customer inquiries from a single screen
```

### タイムスタンプ → 操作タイミング マッピング方法

Whisper の出力から以下のキーワードが登場する秒数を特定して Playwright スクリプトに組み込む：

| シーン | キーワード | Playwright の操作 |
|--------|----------|-----------------|
| Scene 1 | "Sales reps manage" | メール入力開始 |
| Scene 1 | "In this video" | ログインボタンクリック |
| Scene 2 | "Clicking Connect" | OAuth ボタンクリック |
| Scene 2 | "six permissions" | OAuth ダイアログ静止（2秒）|
| Scene 3 | "webhook receives it" | Inbox ポーリング待機開始 |
| Scene 3 | "unread badge appears" | 会話クリック |
| Scene 4 | "reply composer" | 返信フォームフォーカス |
| Scene 4 | "click Send" | 送信ボタンクリック |
| Scene 7 | "automatically applies" | 返信入力開始 |
| Scene 7 | "After 7 days" | disabled な会話を表示 |
| Scene 8 | "signed request" | curl 実行（手動）|

---

## Phase 3: Playwright スクリプト設計

### タイムスタンプ連動の仕組み

```python
import subprocess, time, os
from playwright.sync_api import sync_playwright

AUDIO_DIR = os.path.expanduser("~/Desktop/salesanchor_audio_liam")

# 音声長を事前取得（ffprobe）
def get_duration(scene_num):
    result = subprocess.run(
        ["ffprobe", "-i", f"{AUDIO_DIR}/scene{scene_num}.mp3",
         "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())

# Whisper の結果から特定したタイムスタンプ（秒）
# ※ Phase 2 実行後に実際の値に更新する
TIMESTAMPS = {
    "scene1": {
        "email_input":    5.0,
        "password_input": 8.0,
        "login_click":    12.0,
        "sidebar_hover":  18.0,
    },
    "scene2": {
        "channels_goto":  3.0,
        "connect_click":  8.0,
        "oauth_pause":    15.0,   # 手動操作ポイント
        "active_confirm": 50.0,
    },
    "scene3": {
        "inbox_goto":     2.0,
        "dm_pause":       5.0,    # 手動操作ポイント
        "badge_wait":     20.0,
        "conv_click":     30.0,
    },
    "scene4": {
        "input_focus":    5.0,
        "type_start":     8.0,
        "send_click":     25.0,
        "confirm_pause":  35.0,   # 手動操作ポイント
    },
    "scene5": {
        "channels_goto":  2.0,
        "scroll_start":   5.0,
        "instagram_show": 15.0,
    },
    "scene6": {
        "inbox_goto":     2.0,
        "instagram_tab":  4.0,
        "dm_pause":       8.0,    # 手動操作ポイント
        "conv_click":     25.0,
        "reply_send":     35.0,
        "confirm_pause":  45.0,   # 手動操作ポイント
    },
    "scene7": {
        "lead2_goto":     2.0,
        "input_start":    8.0,
        "send_click":     20.0,
        "label_confirm":  25.0,
        "disabled_show":  40.0,
    },
    "scene8": {
        "devportal_show": 3.0,
        "curl_pause":     8.0,    # 手動操作ポイント
        "response_show":  25.0,
        "status_page":    40.0,
    },
}

def wait_until(scene_start, target_sec):
    """シーン開始からの経過時間に基づいて待機"""
    elapsed = time.time() - scene_start
    remaining = target_sec - elapsed
    if remaining > 0:
        time.sleep(remaining)

def play(scene_num):
    """音声を非同期再生"""
    subprocess.Popen(["afplay", f"{AUDIO_DIR}/scene{scene_num}.mp3"])

def pause(msg):
    """手動操作待機"""
    input(f"\n⏸  {msg}\n   → 完了したら Enter を押してください...")

def safe_click(page, selector, timeout=10000):
    """セレクタが見つからない場合に手動操作を促す"""
    try:
        page.wait_for_selector(selector, timeout=timeout)
        page.click(selector)
    except Exception:
        print(f"⚠️  セレクタ失敗: {selector}")
        pause("手動でクリックして Enter を押してください")
```

### CSS セレクタ定義（Sales Anchor 対応）

```python
SELECTORS = {
    "email_input":    'input[type="email"], input[name="email"]',
    "password_input": 'input[type="password"]',
    "login_button":   'button[type="submit"]',
    "connect_button": 'button:has-text("Connect a Facebook Page"), '
                      'button:has-text("Facebookページを接続")',
    "inbox_link":     'a[href="/lead-chat"], a[href*="lead-chat"]',
    "channels_link":  'a[href="/channels"]',
    "message_input":  'textarea',
    "send_button":    'button:has-text("Send"), button:has-text("送信")',
    "conv_first":     '.conversation-list-item:first-child',
    "instagram_tab":  'button:has-text("Instagram")',
}
```

---

## Phase 4: 各シーンの操作タイミング詳細

### Scene 1（約33秒）— Intro

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 0.0s | login ページを表示 | 自動 |
| 5.0s | メールアドレス入力 | 自動 |
| 8.0s | パスワード入力 | 自動 |
| 12.0s | ログインボタンクリック | 自動 |
| 18.0s | サイドバーをゆっくりハイライト | 自動 |

### Scene 2（約60秒）— OAuth

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 0.0s | /channels へ移動 | 自動 |
| 8.0s | Connect Facebook Page クリック | 自動 |
| 15.0s | OAuth ダイアログ表示 → 2秒静止 | 自動 |
| 15.0s | ⏸ HIGH LIFE JPN Test Page を選択・承認 | **手動** |
| 50.0s | Active 表示を確認 | 自動 |

### Scene 3（約50秒）— Messenger 受信

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 0.0s | /lead-chat へ移動 | 自動 |
| 5.0s | ⏸ Samuraisoul Katana から Messenger DM 送信 | **手動** |
| 20.0s | 未読バッジが出現するまで待機 | 自動 |
| 30.0s | 会話をクリック → Messenger バッジ確認 | 自動 |

### Scene 4（約50秒）— Messenger 返信

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 5.0s | 返信フォームをクリック | 自動 |
| 8.0s | 返信を1文字ずつ入力（50ms 遅延）| 自動 |
| 25.0s | 送信ボタンクリック | 自動 |
| 35.0s | ⏸ 別ブラウザで受信確認 | **手動** |

### Scene 5（約55秒）— Instagram 確認

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 0.0s | /channels へ移動 | 自動 |
| 5.0s | Channels カードをゆっくりスクロール | 自動 |
| 15.0s | Instagram 連携欄をハイライト | 自動 |

### Scene 6（約55秒）— Instagram DM

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 0.0s | /lead-chat → Instagram タブ | 自動 |
| 8.0s | ⏸ samuraisoul_katana から Instagram DM 送信 | **手動** |
| 25.0s | Inbox に Instagram バッジ付き会話が表示 | 自動 |
| 30.0s | 返信入力 → 送信 | 自動 |
| 45.0s | ⏸ 受信確認 | **手動** |

### Scene 7（約60秒）— Human Agent Tag

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 0.0s | /lead-chat?lead_id=2 へ移動（25h 前のメッセージ）| 自動 |
| 8.0s | 返信を入力 | 自動 |
| 20.0s | 送信ボタンクリック | 自動 |
| 25.0s | HUMAN_AGENT ラベルを確認 | 自動 |
| 40.0s | 7日超の会話（送信ボタン disabled）を表示 | 自動 |

### Scene 8（約60秒）— Data Deletion

| タイムスタンプ | 操作 | 自動/手動 |
|-------------|------|---------|
| 0.0s | Meta Developer Portal を表示 | 自動 |
| 8.0s | ⏸ curl コマンドをターミナルで実行 | **手動** |
| 25.0s | レスポンス JSON を表示 | 自動 |
| 40.0s | Status Page URL を開く | 自動 |

---

## 手動操作が必要なポイント（自動化不可の理由）

| シーン | 手動内容 | 自動化できない理由 |
|--------|---------|-----------------|
| Scene 2 | Facebook OAuth 承認 | 外部ドメイン（facebook.com）は Playwright で操作不可 |
| Scene 3 | Samuraisoul Katana から Messenger DM 送信 | 別アカウント・別ブラウザ |
| Scene 4 | 受信確認 | 別ブラウザの確認操作 |
| Scene 6 | samuraisoul_katana から Instagram DM 送信 | 別アカウント・別ブラウザ |
| Scene 6 | 受信確認 | 別ブラウザの確認操作 |
| Scene 8 | curl コマンド実行 | ブラウザ外のターミナル操作 |

---

## 撮影前チェックリスト

| # | 確認項目 | 状態 |
|---|---------|------|
| 1 | Do Not Disturb: ON | |
| 2 | Chrome: Google Translate 無効・拡張機能全て無効・ズーム 100% | |
| 3 | Channels を「切断」済み（Scene 2 用）| |
| 4 | Safari で Samuraisoul Katana ログイン済み | |
| 5 | Scene 7 用 DB 更新済み（lead_id=2 を 25h 前に設定）| ✅ |
| 6 | Whisper でタイムスタンプ取得済み | |
| 7 | salesanchor_recording.py にタイムスタンプ反映済み | |
| 8 | QuickTime: 画面収録の設定完了 | |

---

## 実行コマンド（完全版）

```bash
# Phase 2: Whisper 文字起こし
cd ~/sales-ops-with-claude/02_apps/whisper-tts-tool/local-whisper-ollama
source venv/bin/activate
for i in 1 2 3 4 5 6 7 8; do
  echo "=== Scene $i ==="
  python main.py ~/Desktop/salesanchor_audio_liam/scene${i}.mp3 -l en
done

# Phase 3: タイムスタンプを recording.py に反映（Whisper 結果を見て更新）

# Phase 4: 撮影（QuickTime 録画開始後に実行）
export REVIEW_PASSWORD="review@salesanchor.jpのパスワード"
python3 ~/Desktop/salesanchor_recording.py
```

---

## 成功の判定基準

| 判定項目 | 確認方法 |
|---------|---------|
| 全 8 シーンが 8 分以内 | QuickTime で尺を確認 |
| OAuth が正常に完了 | Scene 2 で Active 表示が映っている |
| Messenger DM が Inbox に表示 | Scene 3 で未読バッジが映っている |
| Instagram DM が Inbox に表示 | Scene 6 で Instagram バッジが映っている |
| HUMAN_AGENT ラベルが表示 | Scene 7 のアウトバウンドバブルに表示 |
| Data Deletion レスポンスが表示 | Scene 8 で confirmation_code が映っている |
