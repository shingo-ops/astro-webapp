/**
 * Google Form → GitHub Issues 自動変換 GAS スクリプト
 *
 * セットアップ手順:
 *   1. Google Form を作成（FEEDBACK_FORM_DESIGN.md の設問に従う）
 *   2. フォームの「スクリプトエディタ」を開く（︙ > スクリプトエディタ）
 *   3. このコードを貼り付ける
 *   4. GITHUB_TOKEN と REPO を設定する
 *   5. onFormSubmit にトリガーを設定する:
 *      「トリガー」→「+トリガーを追加」→
 *      関数: onFormSubmit / イベント: フォームから / 送信時
 *
 * 必要な権限:
 *   - GitHub Personal Access Token（repo スコープ）
 *   - Script Properties に GITHUB_TOKEN を保存（セキュリティのため）
 *
 * 変更履歴:
 *   2026-04-17: 初版作成
 */

// ===== 設定 =====
const REPO = "shingo-ops/salesanchor";  // GitHubリポジトリ

// GitHub Personal Access Token はスクリプトプロパティから取得（ハードコード禁止）
// 設定方法: プロジェクトの設定 > スクリプトプロパティ > GITHUB_TOKEN を追加
function getGitHubToken_() {
  return PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
}

// カテゴリ → GitHub ラベル のマッピング
const CATEGORY_TO_LABEL = {
  "バグ報告": ["bug", "from-form"],
  "機能改善・要望": ["enhancement", "from-form"],
  "使い方がわからない": ["question", "from-form"],
  "その他": ["from-form"],
};

// 重要度 → GitHub ラベル
const PRIORITY_TO_LABEL = {
  "高（業務が止まる）": "priority:high",
  "中（不便だが回避策がある）": "priority:medium",
  "低（改善希望）": "priority:low",
};


// ===== メイン関数（トリガーで呼ばれる） =====

function onFormSubmit(e) {
  try {
    const responses = e.response.getItemResponses();

    // フォーム回答をパース
    const data = {};
    const fieldMap = {
      0: "category",     // Q1: カテゴリ
      1: "title",        // Q2: タイトル
      2: "description",  // Q3: 詳細
      3: "steps",        // Q4: 再現手順
      4: "page",         // Q5: 該当ページ
      5: "priority",     // Q6: 重要度
      6: "screenshot",   // Q7: スクリーンショットURL
      7: "reporter",     // Q8: お名前
      8: "email",        // Q9: メールアドレス
    };

    responses.forEach((item, index) => {
      const key = fieldMap[index];
      if (key) {
        data[key] = item.getResponse() || "";
      }
    });

    // GitHub Issue 本文を構築
    const issueBody = buildIssueBody_(data);

    // ラベルを決定
    const labels = [];
    if (CATEGORY_TO_LABEL[data.category]) {
      labels.push(...CATEGORY_TO_LABEL[data.category]);
    }
    if (PRIORITY_TO_LABEL[data.priority]) {
      labels.push(PRIORITY_TO_LABEL[data.priority]);
    }

    // GitHub Issue を作成
    const issueTitle = `[${data.category || "フィードバック"}] ${data.title || "無題"}`;
    const issueUrl = createGitHubIssue_(issueTitle, issueBody, labels);

    // ログ記録
    Logger.log(`Issue created: ${issueUrl}`);

    // オプション: Discord に通知
    notifyDiscord_(issueTitle, issueUrl, data);

  } catch (error) {
    Logger.log(`Error in onFormSubmit: ${error.message}`);
    // エラーでもフォーム送信自体は成功させる（ユーザーに影響を与えない）
  }
}


// ===== GitHub Issue 作成 =====

function createGitHubIssue_(title, body, labels) {
  const token = getGitHubToken_();
  if (!token) {
    throw new Error("GITHUB_TOKEN がスクリプトプロパティに設定されていません");
  }

  const url = `https://api.github.com/repos/${REPO}/issues`;

  const options = {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
    },
    payload: JSON.stringify({
      title: title,
      body: body,
      labels: labels,
    }),
    muteHttpExceptions: true,
  };

  const response = UrlFetchApp.fetch(url, options);
  const result = JSON.parse(response.getContentText());

  if (response.getResponseCode() !== 201) {
    throw new Error(`GitHub API error: ${response.getResponseCode()} - ${result.message}`);
  }

  return result.html_url;
}


// ===== Issue 本文テンプレート =====

function buildIssueBody_(data) {
  let body = "";

  // ヘッダー（フォーム経由であることを明示）
  body += "> 📋 このIssueはフィードバックフォームから自動作成されました\n\n";

  // 基本情報
  body += `## 概要\n${data.description || "（詳細なし）"}\n\n`;

  // 再現手順（バグの場合）
  if (data.steps) {
    body += `## 再現手順\n${data.steps}\n\n`;
  }

  // メタ情報テーブル
  body += "## 情報\n";
  body += "| 項目 | 内容 |\n";
  body += "|------|------|\n";
  body += `| カテゴリ | ${data.category || "-"} |\n`;
  body += `| 重要度 | ${data.priority || "-"} |\n`;
  body += `| 該当ページ | ${data.page || "-"} |\n`;
  body += `| 報告者 | ${data.reporter || "-"} |\n`;

  if (data.email) {
    body += `| メール | ${data.email} |\n`;
  }

  body += "\n";

  // スクリーンショット
  if (data.screenshot) {
    body += `## スクリーンショット\n${data.screenshot}\n\n`;
  }

  // Claude Code 用メタデータ（機械可読）
  body += "---\n";
  body += "<!-- claude-code-metadata\n";
  body += `page: ${data.page || "unknown"}\n`;
  body += `priority: ${data.priority || "unknown"}\n`;
  body += `category: ${data.category || "unknown"}\n`;
  body += "-->\n";

  return body;
}


// ===== Discord 通知（オプション） =====

function notifyDiscord_(title, issueUrl, data) {
  // Discord Webhook URL をスクリプトプロパティから取得
  const webhookUrl = PropertiesService.getScriptProperties().getProperty("DISCORD_WEBHOOK_URL");
  if (!webhookUrl) return;  // 未設定ならスキップ

  const priorityEmoji = {
    "高（業務が止まる）": "🔴",
    "中（不便だが回避策がある）": "🟡",
    "低（改善希望）": "🟢",
  };

  const embed = {
    title: title,
    url: issueUrl,
    color: data.category === "バグ報告" ? 15158332 : 3447003,  // 赤 or 青
    fields: [
      { name: "重要度", value: `${priorityEmoji[data.priority] || "⚪"} ${data.priority || "-"}`, inline: true },
      { name: "該当ページ", value: data.page || "-", inline: true },
      { name: "報告者", value: data.reporter || "-", inline: true },
    ],
    footer: { text: "Sales Anchor フィードバック" },
    timestamp: new Date().toISOString(),
  };

  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ embeds: [embed] }),
    muteHttpExceptions: true,
  };

  UrlFetchApp.fetch(webhookUrl, options);
}


// ===== 初期セットアップ用ヘルパー =====

/**
 * ラベルが GitHub リポジトリに存在しなければ作成する。
 * 初回セットアップ時に1度だけ実行してください。
 */
function setupGitHubLabels() {
  const token = getGitHubToken_();
  const labelsToCreate = [
    { name: "from-form", color: "c5def5", description: "フィードバックフォーム経由" },
    { name: "bug", color: "d73a4a", description: "バグ報告" },
    { name: "enhancement", color: "a2eeef", description: "機能改善・要望" },
    { name: "question", color: "d876e3", description: "質問" },
    { name: "priority:high", color: "e11d48", description: "高優先度（業務停止）" },
    { name: "priority:medium", color: "f59e0b", description: "中優先度" },
    { name: "priority:low", color: "22c55e", description: "低優先度" },
  ];

  labelsToCreate.forEach(label => {
    const url = `https://api.github.com/repos/${REPO}/labels`;
    const options = {
      method: "post",
      contentType: "application/json",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      payload: JSON.stringify(label),
      muteHttpExceptions: true,
    };

    const response = UrlFetchApp.fetch(url, options);
    if (response.getResponseCode() === 201) {
      Logger.log(`Label created: ${label.name}`);
    } else if (response.getResponseCode() === 422) {
      Logger.log(`Label already exists: ${label.name}`);
    } else {
      Logger.log(`Failed to create label ${label.name}: ${response.getContentText()}`);
    }
  });
}
