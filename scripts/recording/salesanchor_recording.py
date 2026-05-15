"""
Salesanchor Meta App Review - Playwright Recording Script
=========================================================
使用前:
  pip3 install playwright
  python3 -m playwright install chromium

実行:
  export REVIEW_PASSWORD="パスワード"
  python3 ~/Desktop/salesanchor_recording.py
"""

import subprocess
import time
import os
from playwright.sync_api import sync_playwright

AUDIO_DIR = os.path.expanduser("~/Desktop/salesanchor_audio_liam")
BASE_URL = "https://app.salesanchor.jp"


def play(scene: str) -> None:
    """afplay で音声ファイルをバックグラウンド再生"""
    path = f"{AUDIO_DIR}/{scene}.mp3"
    if os.path.exists(path):
        subprocess.Popen(["afplay", path])
    else:
        print(f"  ⚠ 音声ファイルなし: {path}")


def pause(msg: str) -> None:
    """手動操作待ち"""
    print(f"\n⏸  {msg}")
    input("   → 完了したら Enter キーを押してください...")
    print()


def wait(sec: float) -> None:
    time.sleep(sec)


def try_click(page, *selectors):
    """複数セレクターを順に試して最初にヒットした要素をクリック"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                return True
        except Exception:
            pass
    return False


def try_fill(page, value: str, *selectors):
    """複数セレクターを順に試して最初にヒットした入力欄に入力"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(value)
                return True
        except Exception:
            pass
    return False


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=600)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    # =========================================================
    # Scene 1: Introduction — ログイン + ダッシュボード
    # =========================================================
    print("🎬 Scene 1: Introduction")
    page.goto(f"{BASE_URL}/login")
    play("scene1")

    wait(3)
    try_fill(page, "review@salesanchor.jp",
             'input[type="email"]', 'input[name="email"]', '#email')
    wait(1)
    try_fill(page, os.environ.get("REVIEW_PASSWORD", ""),
             'input[type="password"]', 'input[name="password"]', '#password')
    wait(1)
    try_click(page,
              'button[type="submit"]',
              'button:has-text("Login")',
              'button:has-text("Sign in")',
              'button:has-text("ログイン")')
    wait(5)

    # サイドバーのナビリンクをゆっくりホバー
    nav_links = page.locator("nav a, .sidebar a, aside a").all()
    for link in nav_links[:4]:
        try:
            link.hover()
            wait(0.8)
        except Exception:
            pass
    wait(6)

    # =========================================================
    # Scene 2: Channels — Facebook OAuth
    # =========================================================
    print("🎬 Scene 2: Channels / Facebook OAuth")
    page.goto(f"{BASE_URL}/channels")
    play("scene2")
    wait(3)

    # Connect ボタンを探してクリック（ない場合はスキップ）
    connected = try_click(page,
                          'button:has-text("Connect a Facebook Page")',
                          'button:has-text("Facebookページを接続")',
                          'button:has-text("Connect")')
    if connected:
        wait(2)
        pause("Facebook OAuth ダイアログが開きました。\n   HIGH LIFE JPN Test Page を選択して承認してください")
    else:
        print("  → Connect ボタンが見つからないためスキップ（既接続の可能性あり）")

    wait(5)
    # Active バッジ確認のためゆっくりスクロール
    page.evaluate("window.scrollTo(0, 300)")
    wait(2)
    page.evaluate("window.scrollTo(0, 0)")
    wait(8)

    # =========================================================
    # Scene 3: Messenger 受信
    # =========================================================
    print("🎬 Scene 3: Messenger 受信")
    page.goto(f"{BASE_URL}/inbox")
    play("scene3")
    wait(4)

    pause("別ブラウザ（Safari）で Samuraisoul Katana から Messenger DM を送信してください:\n   'Hello, I\\'d like to ask about your products.'")

    # 未読バッジが出るまで最大 20 秒待機
    try:
        page.wait_for_selector(
            ".unread-badge, [data-unread], .badge",
            timeout=20000
        )
    except Exception:
        pass

    wait(2)
    # 最初の会話をクリック
    try_click(page,
              ".conversation-item:first-child",
              ".lead-chat-item:first-child",
              ".inbox-item:first-child",
              "[data-conversation]:first-child")
    wait(5)

    # =========================================================
    # Scene 4: Messenger 返信
    # =========================================================
    print("🎬 Scene 4: Messenger 返信")
    play("scene4")
    wait(4)

    reply_text = (
        "Hi! Thank you for reaching out. "
        "Our products are listed on our website. "
        "Could you share which category interests you?"
    )
    try_fill(page, reply_text,
             "textarea",
             ".message-input",
             '[placeholder*="message"]',
             '[placeholder*="メッセージ"]')
    wait(2)
    try_click(page,
              'button:has-text("Send")',
              'button:has-text("送信")',
              'button[type="submit"]')
    wait(3)

    pause("別ブラウザで Samuraisoul Katana が Messenger で返信を受信したか確認してください")
    wait(3)

    # =========================================================
    # Scene 5: Instagram チャンネル確認
    # =========================================================
    print("🎬 Scene 5: Instagram チャンネル確認")
    page.goto(f"{BASE_URL}/channels")
    play("scene5")
    wait(4)

    # チャンネルカードをゆっくりスクロール
    page.evaluate("window.scrollTo(0, 300)")
    wait(3)
    page.evaluate("window.scrollTo(0, 0)")
    wait(25)

    # =========================================================
    # Scene 6: Instagram DM 送受信
    # =========================================================
    print("🎬 Scene 6: Instagram DM")
    page.goto(f"{BASE_URL}/inbox")
    play("scene6")
    wait(3)

    # Instagram タブへ切り替え
    try_click(page,
              'button:has-text("Instagram")',
              '[data-tab="instagram"]',
              '[data-platform="instagram"]')
    wait(2)

    pause("別ブラウザ（Safari）で samuraisoul_katana から Instagram DM を送信してください:\n   'Hi, do you ship internationally?'")

    try:
        page.wait_for_selector(".unread-badge, [data-unread]", timeout=20000)
    except Exception:
        pass

    wait(2)
    try_click(page,
              ".conversation-item:first-child",
              ".lead-chat-item:first-child",
              ".inbox-item:first-child")
    wait(3)

    ig_reply = (
        "Yes! We ship to over 30 countries. "
        "Please share your country and we'll provide shipping options."
    )
    try_fill(page, ig_reply,
             "textarea",
             ".message-input",
             '[placeholder*="message"]')
    wait(2)
    try_click(page,
              'button:has-text("Send")',
              'button:has-text("送信")',
              'button[type="submit"]')
    wait(3)

    pause("別ブラウザで Instagram 返信を確認してください")
    wait(3)

    # =========================================================
    # Scene 7: Human Agent Tag（25h 経過リード）
    # =========================================================
    print("🎬 Scene 7: Human Agent Tag")
    # lead_id=2 は 25 時間前の inbound メッセージを持つリード
    page.goto(f"{BASE_URL}/inbox?lead_id=2")
    play("scene7")
    wait(5)

    # メッセージ入力
    late_reply = (
        "Sorry for the late reply! "
        "Our team had a one-day off. "
        "Are you still interested in our products?"
    )
    try_fill(page, late_reply,
             "textarea",
             ".message-input",
             '[placeholder*="message"]')
    wait(2)
    try_click(page,
              'button:has-text("Send")',
              'button:has-text("送信")',
              'button[type="submit"]')
    wait(28)

    # =========================================================
    # Scene 8: Data Deletion Callback
    # =========================================================
    print("🎬 Scene 8: Data Deletion Callback")
    page.goto("https://developers.facebook.com/apps")
    play("scene8")
    wait(5)

    pause("Meta Developer Portal で Data Deletion Callback URL を表示してください")
    wait(8)

    pause("ターミナルで curl コマンドを実行してレスポンスを表示してください")
    wait(20)

    # =========================================================
    print("\n✅ 全シーン完了！")
    print("   QuickTime の収録を停止してください。")
    browser.close()
