# Meta App Review — Use Case Descriptions v1.1 (DRAFT)

**この文書について（しんごさん向け）**

これは Google Drive 上の `use_case_descriptions.docx v1.0`（File ID: `14wJpu80wRxM8T5q7JLeHARfeRmXgKD54niij-NOTHFM`）を v1.1 に改訂するためのドラフトです。Master Checklist v1.1 §11 で示された変更（Human Agent Tag 独立化、テスト情報運用ルール、instagram_manage_messages Access Level 検討）と Sales Anchor 表記統一を反映済。

**しんごさんの作業**: 本ドラフトを承認後、Drive の docx を v1.1 に更新（Drive は Master 形式、本 md は repo 内 cross-link 用）。

**Repo 内位置づけ**: `.claude-pipeline/spec.md` の Phase 1-D とは独立。Meta App Review 提出フォームの貼り付け原稿。

---

## v1.0 → v1.1 の変更点サマリ

| 章 | 変更内容 | 根拠 |
|---|---|---|
| **全体** | `Sales Anchor` → `Sales Anchor`（スペース付き）に統一 | しんごさん 2026-04-30 確定（PR #195 で frontend / LP 統一済） |
| **§3.1 pages_messaging** | Human Agent Tag 部分を §3.7 に分離（参照リンク追加） | Master Checklist v1.1 §11.1 |
| **§3.6 instagram_manage_messages** | Advanced Access 申請理由を強化、または段階申請オプション追記 | Master Checklist v1.1 §11.3 |
| **§3.7 Human Agent Tag (新設)** | Permission ではなく Feature として独立記述 | Master Checklist v1.1 §11.1 |
| **§4.2 Data Deletion** | Callback URL を `https://api.salesanchor.jp/api/v1/meta/data-deletion` に修正 | 実装と整合（Phase 5 で api.salesanchor.jp に切替済） |
| **§6.1 Test Tenant Account** | Test Password / Test Instagram の運用ルールを明記（placeholder のまま提出 → 申請直前に差し替え） | Master Checklist v1.1 §11.2 |
| **Revision History** | v1.1 行追加（2026-04-30） | — |

---

# **Meta App Review**

# **Use Case Descriptions**

Permission-by-Permission Justification Document

**Sales Anchor**

Multi-Channel CRM SaaS for B2B Trading Card Game Exporters

**HIGH LIFE JPN**

Representative: Shingo Tanizawa (Sole Proprietor)

https://salesanchor.jp

v1.1   April 30, 2026

---

# **About This Document**

*本書について: App Review 申請フォームに記入する英文を権限別にまとめた資料*

This document provides the official Use Case Descriptions submitted with Sales Anchor's Meta App Review application. Each permission requested is justified with a specific explanation of:

- Why the permission is necessary
- How the permission is used within Sales Anchor
- Which step of the demo screencast demonstrates the usage
- What data is collected and how it is handled

The descriptions are designed to be copy-pasted directly into the Meta App Review submission form.

## **How to Use**

- For each permission below, copy the "Description" text and paste it into the corresponding App Review field.
- Ensure the demo screencast aligns with the referenced timestamps.
- Update version and date when modifying this document.

---

# **1. App Overview**

*アプリ概要 (審査担当者が最初に読む全体説明)*

## **1.1 What is Sales Anchor?**

Sales Anchor is a multi-channel Customer Relationship Management (CRM) SaaS platform designed specifically for Business-to-Business (B2B) Trading Card Game (TCG) exporters operating in Japan. The platform enables businesses to consolidate customer communications from multiple messaging channels—including Facebook Messenger, Instagram Direct Messages, WhatsApp Business, Email, Discord, and Telegram—into a single unified inbox, allowing sales representatives to efficiently manage customer relationships, track deals, and respond to inquiries from qualified business partners worldwide.

The Japanese TCG export industry serves international retailers and collectors who purchase trading cards in bulk quantities. These business transactions often occur via direct messaging on social platforms, with customers reaching out in multiple languages and through various channels. Without a unified CRM solution, TCG exporters frequently lose track of high-value deals, miss response deadlines, and struggle to maintain consistent customer relationships across platforms.

Sales Anchor solves this industry-specific problem by providing a centralized, multi-tenant platform where each client company (tenant) can securely manage their own customer communications while maintaining complete data isolation from other tenants.

## **1.2 Target Users**

Sales Anchor serves two distinct user categories:

- **Primary Users (Tenant Users)**: Business staff at Japanese TCG export companies who log into Sales Anchor to manage customer relationships, send and receive messages, and track deal progress.
- **End Users (Customers)**: International retailers and B2B buyers who contact TCG exporters via Messenger, Instagram DM, or other channels. End Users never log into Sales Anchor directly.

## **1.3 Why Meta Platform Integration is Essential**

In the international B2B TCG trade, Facebook Messenger and Instagram Direct Messages are the primary communication channels for initial customer inquiries and ongoing business relationships. Many international buyers (particularly in Southeast Asia, South America, and Europe) prefer Messenger and Instagram over email or phone for rapid, informal business communication.

Without Meta Platform integration, Sales Anchor cannot function as a CRM for this industry. The ability to receive, view, respond to, and archive Messenger and Instagram DM communications is not a peripheral feature—it is core to the value Sales Anchor delivers to its users.

## **1.4 Business Operations**

| **Attribute** | **Details** |
|---|---|
| Legal Entity | HIGH LIFE JPN (Sole Proprietorship) |
| Representative | Shingo Tanizawa |
| Business Address | GMO Office Support Virtual Office, Japan |
| Service Start Date | June 1, 2026 (planned) |
| Data Hosting | SAKURA internet Inc. (VPS), Japan |
| Primary Service URL | https://salesanchor.jp |
| Privacy Policy URL | https://salesanchor.jp/privacy |
| Terms of Service URL | https://salesanchor.jp/terms |
| Data Deletion URL | https://salesanchor.jp/data-deletion |

---

# **2. Demo Screencast Overview**

*デモ動画の構成: 各権限がどのシーンで確認できるかを示す*

The accompanying demo screencast demonstrates every permission in use. Each permission description in this document references the relevant timestamp. The screencast follows this narrative:

| **Time** | **Scene** | **Permissions Demonstrated** |
|---|---|---|
| 0:00 - 0:30 | Intro: Sales Anchor dashboard overview | — |
| 0:30 - 1:30 | Connect Facebook Page via OAuth 2.0 | pages_show_list, pages_manage_metadata |
| 1:30 - 2:30 | Incoming Messenger message arrives in inbox | pages_messaging, pages_read_engagement |
| 2:30 - 3:30 | Sales rep replies to Messenger message | pages_messaging |
| 3:30 - 4:30 | Connect Instagram Business account | instagram_basic |
| 4:30 - 5:30 | Instagram DM received and replied | instagram_manage_messages |
| 5:30 - 6:30 | Reply outside 24-hour window using Human Agent Tag | Human Agent Tag (Feature, see §3.7) |
| 6:30 - 7:30 | Data Deletion Callback demonstration | (App Review requirement) |

---

# **3. Permission-by-Permission Descriptions**

*権限ごとの説明 (申請フォームに貼り付ける英文)*

## **3.1 pages_messaging**

| | |
|---|---|
| **Permission** | `pages_messaging` |
| **Access Level Requested** | Advanced |
| **Category** | Messenger Platform |
| **Screencast Reference** | 1:30 - 3:30 |

### **Description (for App Review submission field)**

Sales Anchor requests the `pages_messaging` permission to enable core messaging functionality for its CRM users. Specifically, Sales Anchor uses this permission to:

1. **Receive incoming messages via Webhook** from customers who message the connected Facebook Page. When a customer sends a Messenger message to a tenant's Facebook Page, Sales Anchor receives the message via Webhook (signature-verified with HMAC-SHA256) and displays it in the tenant's inbox in real time. This allows business users to see and respond to customer inquiries from a unified CRM interface.

2. **Send outgoing messages** to customers as part of ongoing B2B conversations. When a sales representative types a reply in the Sales Anchor inbox, the message is sent via the Meta Graph API Send API to the customer's Messenger account. All replies are from real human agents (sales representatives at the tenant company); Sales Anchor does not use automated bot replies.

3. **Comply with the 24-hour messaging window** by automatically applying the appropriate `messaging_type`. Messages sent within 24 hours of the last user-initiated message use `messaging_type=RESPONSE` with no tag. For continued customer service conversations beyond the 24-hour window (up to 7 days), Sales Anchor applies the Human Agent Tag (see §3.7 for details). Messages cannot be sent after 7 days; the interface displays an error instructing the user to wait for customer-initiated contact.

Without this permission, Sales Anchor cannot provide its core value proposition—unified CRM-based messaging with B2B customers—to any of its tenants.

### **Data Collected**

- Message content (text and media attachments)
- Page-Scoped ID (PSID) of the sending user
- Timestamp of message
- Message ID (mid) for reply threading

### **Data Retention**

Messages are retained for 3 years in the primary database, then optionally archived according to the tenant's data retention policy, and can be deleted at any time upon user request via the Data Deletion Callback or email to support@salesanchor.jp.

---

## **3.2 pages_manage_metadata**

| | |
|---|---|
| **Permission** | `pages_manage_metadata` |
| **Access Level Requested** | Standard |
| **Category** | Facebook Pages API |
| **Screencast Reference** | 0:30 - 1:30 |

### **Description**

Sales Anchor requests the `pages_manage_metadata` permission to programmatically subscribe and unsubscribe a tenant's Facebook Page to Sales Anchor's Webhook endpoints during the tenant onboarding process.

Specifically, this permission is used in the following flow:

1. When a new tenant connects their Facebook Page via OAuth 2.0, Sales Anchor calls `POST /{page_id}/subscribed_apps` to register the Page for Webhook notifications on the fields: `messages`, `messaging_postbacks`, `message_reactions`, and `message_reads`.
2. When a tenant disconnects their Facebook Page from Sales Anchor, Sales Anchor calls `DELETE /{page_id}/subscribed_apps` to cleanly unsubscribe from Webhooks.

This permission is essential for the multi-tenant architecture of Sales Anchor. Each tenant must be able to independently connect and disconnect their own Facebook Page without manual configuration by Sales Anchor operators. The `pages_manage_metadata` permission enables this self-service Webhook management, which is critical for scalable SaaS operations.

### **Data Collected**

No personal data is collected through this permission. It only manages Webhook subscription states for the connected Pages.

---

## **3.3 pages_show_list**

| | |
|---|---|
| **Permission** | `pages_show_list` |
| **Access Level Requested** | Standard |
| **Category** | Facebook Pages API |
| **Screencast Reference** | 0:45 - 1:15 |

### **Description**

Sales Anchor requests the `pages_show_list` permission to present tenant users with a list of their manageable Facebook Pages during the Page connection flow.

Specifically, after a tenant user authorizes Sales Anchor via Facebook Login, Sales Anchor calls `GET /me/accounts` to retrieve the list of Facebook Pages the user is an admin of. This list is displayed in the Sales Anchor UI, allowing the user to select which specific Page they wish to connect to Sales Anchor.

This permission is essential because many tenant users manage multiple Facebook Pages (for example, a parent company Page and separate product-line Pages). The `pages_show_list` permission allows Sales Anchor to show only the Pages the user actually manages, preventing errors where users attempt to connect a Page they do not have permission to manage.

### **Data Collected**

- Page IDs and Page names of Pages the user manages
- Page category and basic metadata (displayed only, not stored long-term)

---

## **3.4 pages_read_engagement**

| | |
|---|---|
| **Permission** | `pages_read_engagement` |
| **Access Level Requested** | Advanced |
| **Category** | Facebook Pages API |
| **Screencast Reference** | 1:30 - 2:30 |

### **Description**

Sales Anchor requests the `pages_read_engagement` permission to retrieve basic Page information and message engagement data necessary for displaying conversations in the CRM interface.

Specifically, Sales Anchor uses this permission to:

1. Retrieve the public name and profile picture of the Facebook Page (displayed in Sales Anchor's channel settings UI, so users can confirm which Page is connected).
2. Access engagement-related metadata on incoming messages, such as timestamps, read receipts, and reaction events, which are essential for displaying accurate conversation threads in the CRM inbox.
3. Display the public display name and profile picture of the customer (End User) in the conversation view, which is standard UX for any CRM handling Messenger communications.

Without this permission, the CRM inbox would be unable to display basic information about customers, making it difficult for sales representatives to recognize and respond to specific customer inquiries appropriately.

### **Data Collected**

- Page metadata (name, profile picture, category)
- End User public profile info (display name, profile picture) — stored only for the duration of active conversations
- Message engagement events (read receipts, reactions)

---

## **3.5 instagram_basic**

| | |
|---|---|
| **Permission** | `instagram_basic` |
| **Access Level Requested** | Advanced |
| **Category** | Instagram Platform |
| **Screencast Reference** | 3:30 - 4:30 |

### **Description**

Sales Anchor requests the `instagram_basic` permission to identify and display the Instagram Business account linked to a tenant's Facebook Page during the Instagram connection flow.

Specifically, this permission is used to:

1. Retrieve the Instagram Business account ID and display name associated with the connected Facebook Page.
2. Display the Instagram account information in the Sales Anchor UI so that the user can confirm the correct Instagram account is being connected.
3. Verify that the linked Instagram account is a Business or Creator account (required for Instagram Messaging API functionality).

This permission is essential because Sales Anchor supports both Messenger and Instagram Direct Messages as separate channels within the unified inbox. Users need to see which Instagram account is connected, particularly when they manage multiple Instagram Business accounts linked to different Facebook Pages.

### **Data Collected**

- Instagram Business account ID
- Instagram account display name and basic profile information

---

## **3.6 instagram_manage_messages**

| | |
|---|---|
| **Permission** | `instagram_manage_messages` |
| **Access Level Requested** | Advanced |
| **Category** | Instagram Platform |
| **Screencast Reference** | 4:30 - 5:30 |

### **Description**

Sales Anchor requests the `instagram_manage_messages` permission to enable receiving and sending Instagram Direct Messages between tenant businesses and their customers, as a first-class channel within the Sales Anchor CRM.

For B2B TCG exporters in Japan, Instagram DMs are equally as important as Messenger for reaching international customers, particularly in markets where Instagram is the dominant social platform (Brazil, Mexico, Indonesia, Thailand). A large percentage of customer inquiries originate from Instagram Business accounts, and the inability to handle Instagram DMs alongside Messenger would render Sales Anchor incomplete as a multi-channel CRM solution.

**Why Advanced Access is necessary (rather than Standard):**

Standard Access for `instagram_manage_messages` restricts message handling to test users only, which is insufficient for Sales Anchor's multi-tenant production deployment. Tenant businesses operate Instagram Business accounts that interact with real international customers, not test users. To deliver the documented value proposition of unified messaging across Messenger and Instagram, Advanced Access is required from the launch date (June 1, 2026).

If Advanced Access is not initially granted, Sales Anchor would alternatively accept Standard Access during the Beta period (Jun-Aug 2026) with a documented plan to re-apply for Advanced Access after demonstrating sustained compliant usage for 60+ days. However, the preferred path is direct Advanced Access approval to avoid disrupting tenant onboarding.

Specifically, Sales Anchor uses this permission to:

1. Receive incoming Instagram DMs via Webhook (with signature verification) and display them in the tenant's unified inbox alongside Messenger and other channels.
2. Send reply messages authored by human sales representatives at the tenant company. Sales Anchor does not use automated bot replies for Instagram DMs; all replies are typed manually by real staff members and clearly reflect the human agent nature of the conversation.
3. Apply the Human Agent Tag automatically when the sales representative replies between 24 hours and 7 days after the customer's last message (see §3.7), compliant with Instagram Messaging API policies.
4. Handle message reactions and read receipts to maintain accurate conversation state in the CRM.

All Instagram DM usage within Sales Anchor follows Meta's Instagram Messaging API policies. Sales Anchor is designed around the "Human Agent Escalation" model, where human sales representatives manage real B2B conversations—fulfilling the Meta requirement that Instagram Messaging API integrations support human agent involvement.

### **Data Collected**

- Instagram DM message content (text and media attachments)
- Instagram-Scoped ID (IGSID) of the sending user
- Message ID, timestamps, reactions, read receipts

---

## **3.7 Human Agent Tag (Feature, NOT Permission)**

| | |
|---|---|
| **Type** | Messaging Feature |
| **Used With** | `pages_messaging`, `instagram_manage_messages` |
| **Screencast Reference** | 5:30 - 6:30 |
| **Application Field** | Submitted as a Feature in the Meta App Review form (separate from Permissions) |

### **Why this section is separated in v1.1**

In v1.0, Human Agent Tag was described inline within `pages_messaging` (§3.1) and `instagram_manage_messages` (§3.6). However, Meta App Review treats Human Agent Tag as a **Feature**, not a Permission, with its own application field. Reviewers evaluate Permissions and Features in separate sections of the submission form. Therefore, this v1.1 separates the Human Agent Tag justification into its own section (§3.7) for clearer reviewer evaluation.

### **Description**

Sales Anchor uses the Human Agent Tag (`messaging_type=MESSAGE_TAG` with `tag=HUMAN_AGENT`) to enable B2B sales representatives to continue ongoing customer service conversations beyond Meta's standard 24-hour messaging window, while remaining strictly within the bounds of Meta's Human Agent policy.

### **Use Case in Sales Anchor**

In B2B TCG exports, customer conversations frequently span multiple days due to:

- Time zone differences (Japan vs. Latin America / Southeast Asia / Europe)
- Bulk inquiry processing (sales reps batch responses to dozens of inquiries)
- Cross-departmental coordination within the tenant company before responding (inventory check, pricing approval, shipping logistics)

When a customer sends a Messenger or Instagram DM and the human sales representative cannot respond within 24 hours, the Human Agent Tag allows the sales representative to send a follow-up reply between 24 hours and 7 days after the customer's last message. This is functionally equivalent to a human agent returning to a support ticket the next business day.

### **Compliance Mechanisms**

Sales Anchor's design ensures Human Agent Tag is only applied for legitimate human-agent customer service scenarios, never for marketing, broadcast, or automated bot replies. Specifically:

1. **Automatic time-window detection**: When a sales representative composes a reply in the Sales Anchor inbox, the backend automatically calculates the elapsed time since the customer's last message:
   - Within 24 hours → `messaging_type=RESPONSE` (no tag)
   - 24 hours to 7 days → `messaging_type=MESSAGE_TAG` with `tag=HUMAN_AGENT`
   - Beyond 7 days → Send is blocked; UI displays error explaining the customer must initiate contact again.

2. **Human authorship enforcement**: All outgoing messages are typed manually by sales representatives in the inbox interface. Sales Anchor does not provide bulk send, scheduled send, or automated reply functions. The system does not support sending the same message to multiple recipients programmatically.

3. **No marketing/broadcast use**: The Human Agent Tag is never used for marketing campaigns, promotional content, mass messaging, or any non-customer-service purpose. The tag is restricted to direct replies in active customer service conversations.

4. **Audit logging**: Every outbound message tagged with `HUMAN_AGENT` is logged with the sending sales representative's staff ID, timestamp, and target conversation ID. This provides an audit trail demonstrating the human-driven nature of each tagged message.

### **Without the Human Agent Tag**

Without access to this Feature, sales representatives would be unable to respond to customer inquiries received during off-hours or on weekends/holidays without forcing the customer to re-initiate the conversation. This degrades customer experience and creates operational friction in international B2B trade where time-zone gaps are routine.

---

# **4. Compliance and Safety Measures**

*コンプライアンスと安全対策*

## **4.1 Data Protection**

Sales Anchor implements the following technical and organizational measures to protect data obtained through the requested permissions:

- All network communications use TLS 1.3 (HTTPS with Let's Encrypt certificates).
- Access tokens and other sensitive credentials are encrypted at rest using Fernet symmetric encryption.
- Multi-tenant data isolation is enforced at the database level using PostgreSQL Row Level Security (RLS) combined with JWT-based session authentication.
- All incoming Webhook requests are signature-verified using HMAC-SHA256 with the App Secret before any data is stored or processed.
- Data is hosted on SAKURA internet Inc. VPS servers located in Japan. No data is transferred outside Japan for processing.

## **4.2 Data Deletion**

Sales Anchor implements a Data Deletion Callback endpoint at `https://api.salesanchor.jp/api/v1/meta/data-deletion` that handles deletion requests initiated through Meta Platform. Users can also request deletion directly via email at `support@salesanchor.jp`. Complete deletion instructions are published at `https://salesanchor.jp/data-deletion`.

Upon receiving a deletion request, Sales Anchor:

1. Verifies the `signed_request` (for Meta Callback, HMAC-SHA256 with App Secret) or identity (for email requests).
2. Deletes the corresponding data from the primary database within 7 business days.
3. Deletes data from backup systems within 30 days.
4. Issues a confirmation code in the format `DEL-YYYYMMDD-xxxx` for the user to verify deletion status at `https://salesanchor.jp/deletion-status?code=DEL-YYYYMMDD-xxxx`.

## **4.3 Use of Data**

Sales Anchor strictly limits its use of data obtained through the requested permissions to the following purposes:

- Facilitating communication between tenant companies and their B2B customers within the CRM interface.
- Storing conversation history for reference by tenant users (with documented retention periods).
- Complying with Meta Platform policies (24-hour window, Human Agent Tag usage, data deletion).

Sales Anchor explicitly does **NOT** use data obtained through Meta Platform permissions for any of the following:

- Advertising targeting or remarketing.
- Sale to third parties.
- AI model training (neither our own nor third-party models).
- Automated bulk marketing messages.
- Any purpose outside the original B2B CRM use case.

## **4.4 Human Agent Compliance**

Sales Anchor is designed as a tool for human sales representatives to manage customer conversations. All outgoing messages are authored by real human agents typing in the Sales Anchor interface. Sales Anchor does not include automated reply bots, chatbots, or AI-generated message sending functionality for Messenger or Instagram.

This design naturally aligns with Meta's "Human Agent Escalation" requirement for Messenger and Instagram Messaging API applications, as all conversations within Sales Anchor are, by default, handled by human agents. See §3.7 for detailed compliance mechanisms.

---

# **5. Business Justification Summary**

*ビジネス上の正当性のまとめ*

## **5.1 Why These Permissions are Necessary**

Sales Anchor serves a specific and underserved niche: Japanese B2B Trading Card Game exporters who conduct international business via social messaging platforms. This industry has unique characteristics that make Meta Platform integration indispensable:

- International B2B buyers in the TCG industry strongly prefer Messenger and Instagram DM over email, due to speed and informality expected in trading card transactions.
- High-value TCG transactions can be time-sensitive (rare cards become available for a limited time), making rapid response critical to preserving business relationships.
- Existing generic CRM platforms (Salesforce, HubSpot, etc.) do not adequately support the multi-channel messaging needs of this niche industry, nor are they priced appropriately for small-to-medium TCG export businesses.

Without Meta Platform integration, Sales Anchor cannot deliver its core value proposition, and the TCG exporter market will continue to rely on manual, error-prone management of customer conversations across multiple messaging apps.

## **5.2 Expected Impact**

By enabling Sales Anchor, Meta Platform helps:

- Japanese B2B TCG exporters scale their international business more efficiently.
- International TCG retailers and collectors receive faster, more organized responses from suppliers.
- The overall ecosystem of B2B commerce via Messenger and Instagram grows with a responsible, compliant, and transparent CRM implementation.

## **5.3 Commitment to Meta Platform Policies**

Sales Anchor commits to:

- Continuous compliance with Meta Platform Terms and Developer Policies.
- Prompt response to any policy updates or requirement changes from Meta.
- Transparent communication with tenant users about the permissions and data flow.
- Proactive monitoring to prevent policy violations by tenant users (automated detection of spam patterns, bulk sending, etc.).

---

# **6. Test Credentials and Reviewer Access**

*審査担当者向けテスト情報*

For Meta App Reviewers to evaluate Sales Anchor's functionality, the following test credentials and access methods are provided:

## **6.1 Test Tenant Account**

```
Test Account URL:   https://app.salesanchor.jp/login
Test Email:         review@salesanchor.jp
Test Password:      [Provided separately in submission form, see §6.4]
Test Facebook Page: HIGH LIFE JPN
Test Page ID:       664490526747447
Test Instagram:     [Provided separately in submission form, see §6.4]
```

### **6.4 Operational rule for placeholder credentials (NEW in v1.1)**

The Test Password and Test Instagram identifier are intentionally not embedded in this document. Sales Anchor follows Meta's recommended practice of providing sensitive test credentials directly in the submission form (which is encrypted in transit and not retained as a public document) rather than in the Use Case Descriptions document.

**Workflow at submission time:**

1. Sales Anchor team finalizes test credentials immediately before submitting the App Review (within 1 hour of submission).
2. Test Password is provisioned with a dedicated review-only account: `review@salesanchor.jp` granted minimum permissions (read messages, send replies on test Page).
3. Test Instagram credentials are provisioned with a dedicated Test Instagram Business Account, linked to the test Facebook Page (HIGH LIFE JPN).
4. After App Review approval, test credentials are rotated within 7 days (password change, Instagram disconnect/reconnect with new account if needed).

Reviewers can request fresh credentials at any time during the review process by contacting `support@salesanchor.jp` (response within 24 hours).

## **6.2 Recommended Review Flow**

1. Visit `https://app.salesanchor.jp/login` and log in with the provided credentials.
2. Navigate to **Channels** (link in admin dropdown menu) to see the connected Facebook Page and Instagram account.
3. Return to the **Inbox** (`/lead-chat`) to view recent Messenger and Instagram DM conversations.
4. Send a test message to the test Facebook Page (HIGH LIFE JPN) and verify it appears in the Sales Anchor inbox within 5 seconds.
5. Reply from the Sales Anchor inbox and verify the reply arrives in Messenger.
6. Test the Data Deletion flow by submitting a deletion request via the Facebook "Apps and Websites" settings → select "Sales Anchor" → "Remove".

## **6.3 Reviewer Support**

If Meta Reviewers encounter any issues or have questions during the review process, Sales Anchor's review support contact is available:

- **Email**: `support@salesanchor.jp` (monitored Monday–Friday, 10:00–18:00 JST)
- **Response time**: Within 24 hours for reviewer-identified issues
- **Representative**: Shingo Tanizawa

---

# **Revision History**

| **Version** | **Date** | **Changes** |
|---|---|---|
| 1.0 | 2026-04-23 | Initial version for Meta App Review submission |
| **1.1** | **2026-04-30** | Sales Anchor 表記統一 (スペース付き) / §3.7 Human Agent Tag を Feature として独立記述 / §3.6 instagram_manage_messages に Advanced Access 申請理由強化 / §4.2 Data Deletion Callback URL を `api.salesanchor.jp` に修正 (Phase 5 Phase 5 ドメイン切替反映) / §6.4 テスト情報運用ルール明記 |

---

*End of Document*

*HIGH LIFE JPN   Sales Anchor Use Case Descriptions v1.1   2026-04-30 (DRAFT)*

---

## しんごさん作業（DRAFT 承認後）

1. Drive 上の `use_case_descriptions.docx` v1.0 を開く
2. 本ドラフトを参考に v1.1 として全文置換（または diff 適用）
3. ドキュメント名を `use_case_descriptions_v1.1.docx` に rename or 同名で v1.1 として保存
4. Master Checklist v1.1 §10 / §11 の参照を確認、整合あれば Master Checklist にも v1.1 反映を記録
5. Meta App Review 申請フォーム入力時に各 §3.x の Description セクションをコピペ

## 整合確認済リソース

- 実装: `backend/app/routers/meta_inbox.py` / `backend/app/routers/leads.py` / `backend/app/services/meta_graph.py` / `backend/app/routers/webhook.py` / `backend/app/routers/meta.py`
- ドキュメント: `docs/PHASE_1D_META_INBOX_OVERVIEW.md` / `docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md` / `docs/data_deletion_callback_design.md`
- 設定: VPS `.env` の `META_OAUTH_REDIRECT_URI` / `META_APP_ID`
