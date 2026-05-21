"""PO メール送信 (Sprint 8 / F8)

設計:
  - 既存 email_sender.py の SMTP infra (環境変数 + idle fallback) を踏襲。
  - 添付 PDF (po_renderer から取得) を MIMEMultipart に乗せる。
  - 件名 / 本文は po_renderer.build_email_subject_and_body() を使用。
  - 失敗時は呼出元 (router) が PO status を 'error' に更新できるよう、
    SendResult を返す純粋関数として実装。

呼出元:
  backend/app/routers/purchase_orders.py
    POST /api/v1/purchase-orders/{id}/send-email
    POST /api/v1/purchase-orders/{id}/resend-email

関連:
  .claude-pipeline/spec.md F8 / AC8.2 / AC8.5
  backend/app/services/email_sender.py (SMTP base)
  backend/app/services/po_renderer.py (PDF + 件名/本文 builder)
"""
from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    """email_sender._smtp_configured() と同じ条件。"""
    return all([
        os.getenv("SMTP_HOST"),
        os.getenv("SMTP_USER"),
        os.getenv("SMTP_PASSWORD"),
        os.getenv("MAIL_FROM"),
    ])


@dataclass
class SendResult:
    success: bool
    error: str | None = None  # SMTP / OS error message (when success=False)
    skipped: bool = False     # SMTP 未設定で idle 動作した場合


def send_po_email_sync(
    to_addr: str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes,
    pdf_filename: str,
    smtp_overrides: dict | None = None,
) -> SendResult:
    """同期 SMTP 送信。aiosmtpd local server / mailhog でも捕捉できる。

    smtp_overrides で host/port/user/password/mail_from を上書き可能。
    テスト時は aiosmtpd の Controller を起動し port を渡す。

    Args:
        to_addr: 宛先メールアドレス。
        subject: 件名 (UTF-8)。
        body_text: 本文 plain text。
        pdf_bytes: 添付 PDF バイト列。
        pdf_filename: PDF ファイル名 (ASCII / 日本語可だが ASCII 安全)。
        smtp_overrides: テスト用に SMTP 接続情報を上書き。

    Returns:
        SendResult(success, error, skipped)
    """
    overrides = smtp_overrides or {}

    def _g(key: str, default: str = "") -> str:
        return overrides.get(key) or os.getenv(key.upper(), default)

    if not (overrides or _smtp_configured()):
        logger.info(
            "[po_mailer] SMTP not configured, skipping send (to=%s, subject=%r)",
            to_addr, subject,
        )
        return SendResult(success=False, skipped=True)

    host = _g("smtp_host", "")
    port = int(_g("smtp_port", "587") or "587")
    user = _g("smtp_user", "")
    password = _g("smtp_password", "")
    mail_from = _g("mail_from", "noreply@salesanchor.jp")
    use_tls = overrides.get("use_tls", True)  # テストで aiosmtpd 利用時 False に

    msg = MIMEMultipart()
    msg["From"] = mail_from
    msg["To"] = to_addr
    msg["Subject"] = subject

    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header(
        "Content-Disposition", "attachment", filename=pdf_filename,
    )
    msg.attach(attachment)

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        logger.info("[po_mailer] PO email sent: %s -> %s (%d bytes attachment)",
                    subject, to_addr, len(pdf_bytes))
        return SendResult(success=True)
    except Exception as e:  # noqa: BLE001
        logger.error("[po_mailer] send failed (to=%s, subject=%r): %s",
                     to_addr, subject, e, exc_info=True)
        return SendResult(success=False, error=str(e))
