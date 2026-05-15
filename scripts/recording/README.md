撮影手順（Salesanchor Meta App Review）
=========================================

【事前準備】
1. pip3 install playwright
2. python3 -m playwright install chromium
3. ~/Desktop/salesanchor_audio_liam/ に scene1.mp3〜scene8.mp3 があることを確認

【撮影手順】
1. QuickTime Player を起動 → ファイル → 新規画面収録 → 収録開始
2. ターミナルで以下を実行:

   export REVIEW_PASSWORD="パスワードをここに入力"
   python3 ~/Desktop/salesanchor_recording.py

3. スクリプトが自動で画面操作を行う
4. "⏸" の表示が出たら手動操作を行い、完了後 Enter キーを押す
5. 全シーン完了後 QuickTime で収録停止

【手動操作が必要なシーン】
- Scene 2: Facebook OAuth（HIGH LIFE JPN Test Page を選択して承認）
- Scene 3: 別ブラウザで Messenger DM 送信
- Scene 4: 別ブラウザで Messenger 受信確認
- Scene 6: 別ブラウザで Instagram DM 送信・受信確認
- Scene 8: Meta Developer Portal 表示 + curl コマンド実行

【注意】
- REVIEW_PASSWORD は review@salesanchor.jp のパスワード
- Scene 7 のリードは DB で last_inbound_at を25時間前に設定済み
