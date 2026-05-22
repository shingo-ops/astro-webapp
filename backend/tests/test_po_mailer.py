"""PO mailer のテスト (Sprint 8 / F8 / AC8.2, AC8.5)

設計:
  - aiosmtpd の Controller を pytest fixture でローカル SMTP サーバとして起動。
    ローカル環境によっては 127.0.0.1 自己接続が制限されている (macOS 一部) ため、
    aiosmtpd が start に失敗した場合は smtplib.SMTP の monkey patch で
    capture する代替フィクスチャを使う (テストの本質は SMTP プロトコル疎通
    ではなく「メール件名 / 本文 / 添付の組み立て」)。
  - 失敗ケース (host=unreachable) で SendResult.success=False, error 詳細あり

AC マッピング:
  AC8.2: test_send_po_email_captures_attachment_pdf
  AC8.5: test_send_po_email_returns_failure_on_unreachable_smtp
"""
from __future__ import annotations

import email
from email.message import Message
from typing import Any

import pytest


# ─────────────────────────────────────────────────────────────────────
# Local SMTP server fixture (aiosmtpd) + smtplib monkey patch fallback
# ─────────────────────────────────────────────────────────────────────

class _CapturingHandler:
    """aiosmtpd のメッセージハンドラ。受信メールをリストに保存する。"""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:  # noqa: N802, ARG002
        msg = email.message_from_bytes(envelope.content)
        self.messages.append(msg)
        return "250 OK"


class _SmtpStub:
    """smtplib.SMTP の代替: 送信メッセージを captured_messages に保存。"""

    captured_messages: list[Message] = []

    def __init__(self, host, port, timeout=None):  # noqa: ARG002
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc):  # noqa: D401
        return False

    def starttls(self):  # noqa: D401
        return None

    def login(self, user, password):  # noqa: ARG002, D401
        return None

    def send_message(self, msg):  # noqa: D401
        # コピーして保存
        _SmtpStub.captured_messages.append(msg)
        return {}


@pytest.fixture
def smtp_capture(request, monkeypatch):
    """まず aiosmtpd を試す。失敗したら smtplib モンキーパッチに fallback。"""
    handler = _CapturingHandler()

    # aiosmtpd ベース
    try:
        from aiosmtpd.controller import Controller
        controller = Controller(handler, hostname="127.0.0.1", port=0)
        try:
            controller.start()
        except OSError:
            # macOS の 127.0.0.1 自己接続不可など: fallback
            raise ImportError("aiosmtpd local server failed to start, falling back")
        port = controller.port

        def _cleanup():
            controller.stop()
        request.addfinalizer(_cleanup)
        return ("aiosmtpd", handler, port)
    except (ImportError, OSError):
        pass

    # fallback: smtplib モンキーパッチ
    _SmtpStub.captured_messages = []
    monkeypatch.setattr("app.services.po_mailer.smtplib.SMTP", _SmtpStub)
    return ("monkeypatch", _SmtpStub, 0)


@pytest.fixture
def pdf_bytes_sample():
    """テスト用 PDF bytes。実 PDF でなくとも MIMEApplication が乗れば OK。"""
    return b"%PDF-1.4\n%TEST\n" + b"X" * 200


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

def test_send_po_email_captures_attachment_pdf(smtp_capture, pdf_bytes_sample):
    """AC8.2: 添付 PDF + 件名 + 本文が SMTP 経由でキャプチャされる。

    aiosmtpd が起動できる環境では実 SMTP プロトコル疎通、できない環境では
    smtplib モンキーパッチで送信内容のみキャプチャ。本質は組み立て内容の検証。
    """
    from app.services.po_mailer import send_po_email_sync

    mode, captor, port = smtp_capture
    result = send_po_email_sync(
        to_addr="ops@example.com",
        subject="【発注書】QA テナント株式会社 PO-00001",
        body_text="リザ eX SAR × 3\nお願いします",
        pdf_bytes=pdf_bytes_sample,
        pdf_filename="PO-00001.pdf",
        smtp_overrides={
            "smtp_host": "127.0.0.1",
            "smtp_port": str(port),
            "use_tls": False,
            "mail_from": "noreply@test.salesanchor.jp",
        },
    )
    assert result.success is True, f"send failed in mode={mode}: {result.error}"
    assert result.error is None

    if mode == "aiosmtpd":
        messages = captor.messages
    else:
        messages = captor.captured_messages

    assert len(messages) == 1

    msg = messages[0]
    assert "PO-00001" in (msg["Subject"] or "")
    assert "ops@example.com" in (msg["To"] or "")

    # 添付確認: multipart の中に application/pdf がある
    parts = list(msg.walk())
    pdf_parts = [p for p in parts if p.get_content_type() == "application/pdf"]
    assert len(pdf_parts) >= 1
    pdf_part = pdf_parts[0]
    assert pdf_part.get_payload(decode=True) == pdf_bytes_sample
    cd = pdf_part.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "PO-00001.pdf" in cd

    # 本文に alias_text が含まれる (AC8.2)
    body_parts = [p for p in parts if p.get_content_type() == "text/plain"]
    body_text = "\n".join(p.get_payload(decode=True).decode("utf-8") for p in body_parts)
    assert "リザ eX SAR" in body_text


def test_send_po_email_returns_failure_on_unreachable_smtp(pdf_bytes_sample):
    """AC8.5: SMTP host 不正 → SendResult.success=False"""
    from app.services.po_mailer import send_po_email_sync

    result = send_po_email_sync(
        to_addr="ops@example.com",
        subject="dummy",
        body_text="dummy body",
        pdf_bytes=pdf_bytes_sample,
        pdf_filename="dummy.pdf",
        smtp_overrides={
            "smtp_host": "127.0.0.1",
            # 使われていないであろう高ポート
            "smtp_port": "59999",
            "use_tls": False,
            "mail_from": "noreply@test.salesanchor.jp",
        },
    )
    assert result.success is False
    assert result.skipped is False
    assert result.error is not None
    assert len(result.error) > 0


def test_send_po_email_idle_when_smtp_not_configured(pdf_bytes_sample, monkeypatch):
    """SMTP 未設定環境では skipped=True で idle 動作 (本番事故防止)。"""
    from app.services import po_mailer

    # 全 SMTP env を削除
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM"):
        monkeypatch.delenv(k, raising=False)

    result = po_mailer.send_po_email_sync(
        to_addr="ops@example.com",
        subject="dummy",
        body_text="dummy",
        pdf_bytes=pdf_bytes_sample,
        pdf_filename="dummy.pdf",
        smtp_overrides=None,
    )
    assert result.skipped is True
    assert result.success is False
