# ADR-068: プラットフォームブランドアセットポリシー

## ステータス
Accepted (2026-05-23)

## コンテキスト

SalesAnchor は Meta API（Messenger / Instagram / WhatsApp）を統合しているため、
Meta Developer Platform Policy に準拠する義務がある。Policy §3（Branding）では
公式ブランドアセットの使用が義務付けられており、非公式・改変されたロゴの使用は
アプリ審査での不合格・API 停止リスクにつながる。

同様に Discord・Telegram も独自のブランドガイドラインを持ち、公式アセットの使用を推奨（または義務化）している。

現状、`frontend/public/brand-icons/` に静的ファイルとして保存しているため、
プラットフォームがロゴを変更しても気づかないリスクがある。
Meta ロゴ変更頻度は数年に一度、審査サイクルは月単位であるため
週次ではなく **四半期監視** が現実的なリスクに見合った対応である。

## 決定事項

### 1. 公式アセット必須ルール

全プラットフォームのアイコンは、各社公式ブランドリソースセンターのアセットのみ使用する。
代替（simple-icons 等）への切り替えは、公式アセットの取得が永続的に不可能と判断された場合のみ許可する。

| プラットフォーム | 公式取得元 | 保存先 | 備考 |
|---|---|---|---|
| Messenger | meta.com/brand/resources/facebook/messenger-icon/ | `messenger.svg` | Meta 公式青円 SVG |
| Instagram | meta.com/brand/resources/instagram/instagram-brand/ | `instagram.png` | 公式 PNG を 96px にリサイズ（公式 SVG は印刷用高解像度のため） |
| WhatsApp | meta.com/brand/resources/whatsapp/whatsapp-brand/ | `whatsapp.svg` | 公式グリーン SVG |
| Discord | discord.com/branding | `discord.svg` | Discord Symbol Blurple SVG |
| Telegram | telegram.org/img/t_logo.svg | `telegram.svg` | 直 URL で取得可能（安定） |

### 2. アセット管理ファイル

- **取得元 URL**: `frontend/src/constants/icons.tsx` のコメントに取得日・取得元を記載
- **バージョン基準値**: `.github/brand-icon-versions.json` に以下を記録
  - `simple_icons`: 参照用 simple-icons パッケージバージョン（変更検知の canary として使用）
  - `assets.telegram.sha256`: Telegram SVG の SHA256（直 URL なので checksum で監視）
  - `last_checked`: 最終確認日

### 3. 四半期監視・自動 PR（Dependabot パターン）

`.github/workflows/brand-asset-monitor.yml` が四半期ごとに以下を実行する:

1. simple-icons の最新リリースタグを GitHub API で取得し、ベースラインと比較
2. Telegram SVG の SHA256 を curl で取得し、ベースラインと比較
3. 変化を検知した場合:
   - Telegram・Discord: 自動でダウンロードしてコミット
   - Meta 3 社: Playwright で公式ブランドページから ZIP を取得・展開
   - 新ブランチに push し **PR を自動作成**（`auto-generated` ラベル）
4. CI runner が Meta ページにブロックされた場合: フォールバック Issue を起票して手動対応を促す

### 4. マージポリシー

自動 PR は人間が視覚確認してからマージする（自動マージしない）。
- PR の Files changed で各アイコンの外観変化を確認
- CI 全チェック通過を確認してからマージ

## 棄却した案

### A. simple-icons を devDependencies 化 + Dependabot

simple-icons はモノクロ・シンプル版（単色 SVG）を提供するが、
Instagram グラデーション・Messenger 公式青など公式フルカラーアセットへの **降格** になるため不採用。
simple-icons は変更検知の canary としてのみ利用する。

### B. Playwright ビジュアル監視（pHash）

Meta.com のレイアウト変更・CAPTCHA・セレクタ腐敗による偽陽性リスクが高く、
維持コストが検知価値を上回るため **監視用途では** 不採用。
ダウンロード用途では引き続き Playwright を使用する。

### C. 週次監視

Meta ロゴ変更は数年に一度。審査サイクル（月単位）より短い週次は過剰であり、
ノイズになるため四半期に変更した。

## 影響範囲

| ファイル | 役割 |
|---|---|
| `frontend/public/brand-icons/` | アセット配置場所 |
| `frontend/src/constants/icons.tsx` | 取得元コメント・描画ロジック |
| `.github/brand-icon-versions.json` | バージョン基準値（SPoT） |
| `.github/workflows/brand-asset-monitor.yml` | 四半期監視・自動 PR ワークフロー |
| `scripts/download-brand-assets.js` | Playwright ダウンロードスクリプト（CI・手動共用） |
