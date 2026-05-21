# Inventory Parser Samples - Fixture

## 概要
Jarvis CRM Sprint 3 AC3.2 の「raw_content パーサー」テスト用 fixture。
Google スプレッドシート「API解析シート」から抽出した実データのメッセージ原文 5 件。

## 出典
- **ファイル**: Google Drive `highlife-jpn_inventory-analytics`
- **シート**: 「API解析シート」（仕入元別タブ）
- **行**: ① [メッセージ原文]
- **抽出日**: 2025-05-21

## 含まれるサンプル

| # | 仕入元 | 文字数 | 表現スタイル | 主な商品類 |
|---|--------|--------|--------------|----------|
| 1 | シンソク | 1,170 | 箇条書き＋状態記号 | ポケモンカード拡張パック（状態分け販売） |
| 2 | 島田 | 997 | 箇条書き＋カートン/BOX混在 | 複数TCG商品（遊戯王・ポケモン・ワンピース） |
| 3 | イセキ | 1,280 | 構造化リスト＋詳細ポリシー | ポケモンカード中心（シュリンク有無表記） |
| 4 | Yasu Kishi | 1,106 | 技術的＋単位記載詳細 | ポケモンカード・ワンピースの Case/Box 混在 |
| 5 | 三海 | 1,061 | セール表示＋日本語版表記 | 複数TCG・ポケモンセンター品混在 |

## パーサー挙動の期待値

### 単位の揺れ（AC3.2 正規化対象）
- 「BOX」vs「Box」vs「ボックス」
- 「カートン」vs「ケース」vs「CASE」vs「case」
- 「パック」vs「pack」の混在

### 価格表記の多様性
- 「@価格」形式（シンソク、Yasu Kishi）
- 「価格/単位」形式（三海）
- 「●商品名 価格 数量」形式（島田）

### 商品状態の表記
- 「[通常品]」「[状態A-]」「[状態B]」（シンソク）
- 「(シュリ有)」「(シュリ無)」（イセキ）
- 括弧なし混在（三海）

### 送料・政策の記載位置
- メッセージ末尾に集約（シンソク）
- インライン（島田）
- 独立セクション化（イセキ）

## マスキング処理
- 金額の具体的数値は `XXX,XXX円` で代替（一部サンプル）
- 個人電話番号は削除（該当なし）
- 企業名・住所は保持

## Sprint 3 Generator での使用方法

### 1. raw_content → normalized_inventory 変換テスト
```python
from backend.tests.fixtures.inventory_parser_samples import load_sample
sample = load_sample(1)
result = parse_inventory_message(sample['raw_content'])
assert result['items_count'] == sample['expected_items_count']
```

### 2. 単位正規化テスト（AC3.2）
- 各サンプルから BOX/カートン の揺れをバリエーション検証
- 「ニンジャスピナー 11,800円×30BOX」vs「11,800×30box」の同一化テスト

### 3. 多仕入元コンテキスト学習
- 仕入元ごとのメッセージ形式の多様性を学習
- Parser が「この表記=このスタイル」で型推定できるか検証

## 注意事項
- 仕入元名は社内情報だが、メッセージ原文は fixture として git 管理許容
- 実データの一部を使用しているため、本番配信前にメッセージ内容の確認を推奨
- 「ARカード」「SR」など TCG 用語は専門領域：マスキング不要

## 関連ドキュメント
- AC3.2: 在庫メッセージ正規化パイプライン
- `backend/inventory_parser.py`: メイン実装
- `backend/models/inventory.py`: スキーマ定義
