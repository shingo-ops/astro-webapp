"""
Contact Form Endpoint — LP問い合わせ受付

POST /api/v1/contact
- 認証不要（salesanchor.jp LP から送信）
- 入力: name, email, company
- 動作: 管理者メール(support@salesanchor.jp)に転送、SMTP未設定時はログのみ
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.schemas.base import validate_email_loose

router = APIRouter()
logger = logging.getLogger(__name__)

ADMIN_EMAIL = os.getenv("CONTACT_NOTIFY_EMAIL", "support@salesanchor.jp")


class ContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=255)
    company: str = Field(..., min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_loose(v)


def _smtp_configured() -> bool:
    return all([
        os.getenv("SMTP_HOST"),
        os.getenv("SMTP_USER"),
        os.getenv("SMTP_PASSWORD"),
        os.getenv("MAIL_FROM"),
    ])


def _send_notification(data: ContactRequest) -> None:
    if not _smtp_configured():
        logger.info(
            "[contact] SMTP not configured — contact request received: "
            f"name={data.name!r} email={data.email!r} company={data.company!r}"
        )
        return

    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    mail_from = os.getenv("MAIL_FROM", "")

    subject = f"[Sales Anchor] Early Access Request — {data.company}"
    body = f"""Early access request received from the LP.

Name:    {data.name}
Email:   {data.email}
Company: {data.company}

---
Reply to: {data.email}
"""

    msg = MIMEMultipart("alternative")
    msg["From"] = mail_from
    msg["To"] = ADMIN_EMAIL
    msg["Reply-To"] = data.email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


@router.post("/contact")
async def submit_contact(data: ContactRequest):
    """LP問い合わせフォーム受付。管理者へメール転送して200を返す。"""
    try:
        _send_notification(data)
    except Exception:
        logger.exception("[contact] failed to send notification email")
        # メール送信失敗でも受付成功として返す（UX優先・ログで補完）

    logger.info(
        f"[contact] received: name={data.name!r} email={data.email!r} "
        f"company={data.company!r}"
    )
    return {"status": "received"}
