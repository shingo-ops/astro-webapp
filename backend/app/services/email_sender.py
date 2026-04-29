"""
SMTP メール送信ヘルパー (B6)

Meta Data Deletion Callback の完了通知メールを送る。
さくらメール SMTP（または互換 SMTP）想定。

環境変数:
- SMTP_HOST: SMTP サーバー（例: mail6.sakura.ne.jp）
- SMTP_PORT: SMTP ポート（デフォルト 587）
- SMTP_USER: ログイン名
- SMTP_PASSWORD: パスワード
- MAIL_FROM: 送信元アドレス（例: support@salesanchor.jp）

未設定時は **idle**（送信せず log のみ）。Meta App Review テストではメール送信は必須ではない。
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql://"
)


def _smtp_configured() -> bool:
    return all([
        os.getenv("SMTP_HOST"),
        os.getenv("SMTP_USER"),
        os.getenv("SMTP_PASSWORD"),
        os.getenv("MAIL_FROM"),
    ])


def _send(to_addr: str, subject: str, body_text: str) -> None:
    """SMTP で送信。未設定なら idle。"""
    if not _smtp_configured():
        logger.info(
            "[email_sender] SMTP not configured, skipping send "
            f"(to={to_addr}, subject={subject!r})"
        )
        return

    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    mail_from = os.getenv("MAIL_FROM", "")

    msg = MIMEMultipart("alternative")
    msg["From"] = mail_from
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


# ───────────────────────────────────────
# Public functions
# ───────────────────────────────────────

def send_deletion_completion_email(request_id: str) -> None:
    """
    削除完了通知メールを送信する（仕様書 §3.4 テンプレート）。

    Meta callback flow ではエンドユーザーのメールは未取得 → 送信スキップ。
    email channel flow（手動）では identifier_value にメールアドレスが入る想定 → 送信。
    """
    engine = create_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(engine)

    with Session() as session:
        row = session.execute(
            text("""
                SELECT
                    request_id,
                    confirmation_code,
                    channel,
                    user_type,
                    identifier_type,
                    identifier_value,
                    completed_at,
                    data_items_deleted
                FROM public.data_deletion_logs
                WHERE request_id = :rid
                LIMIT 1
            """),
            {"rid": request_id},
        ).first()

    if row is None:
        logger.warning(f"[email_sender] request_id={request_id} not found")
        return

    (
        rid,
        code,
        channel,
        user_type,
        ident_type,
        ident_value,
        completed_at,
        data_items_deleted,
    ) = row

    # メール送信先の決定
    if channel == "email" and ident_type == "email":
        to_addr = ident_value
    else:
        # Meta callback の場合は宛先不明 → 送信しない（log のみ）
        logger.info(
            f"[email_sender] no email destination for {rid} "
            f"(channel={channel}, identifier_type={ident_type})"
        )
        return

    if not to_addr:
        logger.warning(f"[email_sender] empty email destination for {rid}")
        return

    completed_str = (
        completed_at.strftime("%Y-%m-%d %H:%M JST") if completed_at else "（処理中）"
    )

    subject = f"【完了】データ削除申請 / Data Deletion Completed [{code}]"
    body = f"""お客様

データ削除申請 (受付番号: {rid}) の処理が完了しました。

【削除完了】
・確認コード: {code}
・削除完了日時: {completed_str}
・削除項目: {data_items_deleted or '監査ログご参照'}

【状況確認URL】
https://salesanchor.jp/deletion-status?code={code}

30日以内にバックアップからも完全削除されます。

ご利用ありがとうございました。

---------------------------------------------
Your data deletion request (Case #{rid}) has been completed.

[Completed]
- Confirmation code: {code}
- Completion time: {completed_str}
- Deleted items: see audit log

[Status URL]
https://salesanchor.jp/deletion-status?code={code}

Full deletion from backups will complete within 30 days.
---------------------------------------------

HIGH LIFE JPN
support@salesanchor.jp
"""

    try:
        _send(to_addr, subject, body)
        logger.info(f"[email_sender] completion email sent: {rid} -> {to_addr}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"[email_sender] send failed: {e}", exc_info=True)
        raise


def send_deletion_acknowledgment_email(request_id: str) -> None:
    """
    受領確認メール（仕様書 §3.3 テンプレート）。
    email channel flow で受領直後に送信する想定。Meta callback flow では未使用。
    """
    # send_deletion_completion_email と同じ流れだが本文がテンプレ §3.3
    # email channel flow は手動運用が前提のため、初回実装ではスキップしても問題なし。
    # 将来 email channel の自動受付 API を作る時に実装する。
    logger.info(
        f"[email_sender] acknowledgment send for {request_id} not implemented yet"
    )
