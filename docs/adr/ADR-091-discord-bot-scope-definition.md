# ADR-091: Discord Bot 担当業務スコープ定義

## Status

Proposed

## Date

2026-06-02

## Context

Sales Anchor は B2B SaaS CRM として、顧客とのコミュニケーション基盤に Discord を活用している。
現状、担当者・顧客ともに Discord アプリを直接操作する必要があり、Sales Anchor アプリとの往復が発生している。

この非効率を解消するため、Discord Bot を Sales Anchor に統合し、
**担当者も顧客も Discord を直接操作しなくても Sales Anchor アプリ上で全てが完結する**
状態を目指す。

## KGI

> Discord サーバーに入らなくても、Sales Anchor アプリで同等の使用感を実現し、アプリ内で全て完結させる

## Decision

Discord Bot の担当業務を以下 7 項目と定義する。

### 1. プライベートチャンネルでの顧客コミュニケーション・受発注

- 担当者が Sales Anchor アプリから顧客専用プライベートチャンネルでメッセージを送受信できる
- 受発注のやり取りもチャンネル内で完結できる

### 2. アナウンス情報の発信

- 新着情報をアプリから Discord の指定チャンネルへ配信できる
- サーバー内コミュニティ限定情報（メンバー限定告知等）を発信できる

### 3. チケットツールによる顧客専用チャンネルの自動発行

- 顧客が Discord サーバーに参加したタイミングで Bot が検知する
- チケットツールを介して担当者とのコミュニケーション専用プライベートチャンネルを自動作成する

### 4. 顧客規模別専用チャンネルの管理・情報発信

- 小口・大口の顧客規模別に専用チャンネルを作成・管理する
- 規模ごとに異なる価格帯・商品情報・在庫情報を発信する

### 5. チャンネル招待メッセージの送信

- 担当者が Sales Anchor アプリから顧客へのチャンネル招待メッセージを送信できる

### 6. アプリからの顧客削除操作

- アプリ側で顧客を特定チャンネルから削除できる
- アプリ側で顧客を Discord サーバーから削除（Kick/BAN）できる

### 7. 顧客規模と連動したロール自動付与

- Sales Anchor アプリ上の顧客規模（小口・大口）変更に連動して Discord ロールを自動付与・更新する
- 規模変更時はロールも即時反映する

## Scope（対象外）

- Discord サーバーの初期構築・チャンネル設計（人手で行う）
- Bot を介さない Discord 上での直接操作（担当者が行う場合は対象外）
- 音声チャンネルの管理

## Consequences

- 担当者の Discord 直接操作が不要になり、Sales Anchor アプリ上で顧客管理が完結する
- Discord Bot の権限設計・API 実装を Sales Anchor backend に追加する必要がある
- 顧客規模フィールド（小口・大口）が Sales Anchor の顧客データと Discord ロールの SSOT になる
- チャンネル・ロール管理の操作ログを Sales Anchor 側で記録する設計が必要

## Related

- ADR-009: Discord Gateway（在庫解析・DM受信箱の基盤）
- `backend/app/discord_gateway/` — 既存の Gateway 実装
- memory: `project_discord_bot_kgi_kpi.md`
