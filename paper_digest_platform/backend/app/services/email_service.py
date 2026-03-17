from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import get_settings


class EmailService:
    async def send_verification_code(self, to_email: str, code: str, purpose: str) -> None:
        settings = get_settings()
        smtp_cfg = {
            "smtp_host": settings.verify_smtp_host,
            "smtp_port": settings.verify_smtp_port,
            "use_tls": settings.verify_smtp_use_tls,
            "use_ssl": settings.verify_smtp_use_ssl,
            "username": settings.verify_smtp_username,
            "password": settings.verify_smtp_password,
            "from": settings.verify_smtp_from_email or settings.verify_smtp_username,
            "timeout_s": settings.verify_smtp_timeout_seconds,
        }
        if not smtp_cfg["smtp_host"] or not smtp_cfg["from"]:
            raise ValueError("未配置验证码发信 SMTP（verify_smtp_*）")

        title_suffix = "注册" if purpose == "register" else "重置密码"
        subject = f"论文推送平台{title_suffix}验证码"
        text_body = (
            f"你的验证码是：{code}\n"
            "有效期 10 分钟。\n"
            "如果这不是你的操作，请忽略本邮件。"
        )
        html_body = (
            "<html><body style='font-family:Arial,sans-serif;'>"
            "<h2>论文推送平台验证码</h2>"
            f"<p>你的验证码是：<b style='font-size:24px;color:#1d4ed8'>{code}</b></p>"
            "<p>有效期 10 分钟。如果这不是你的操作，请忽略本邮件。</p>"
            "</body></html>"
        )
        await self.send_email(smtp_cfg=smtp_cfg, to_emails=[to_email], subject=subject, text_body=text_body, html_body=html_body)

    async def send_test_email(
        self,
        *,
        smtp_cfg: dict[str, object],
        to_email: str,
        username: str,
    ) -> None:
        subject = "论文推送平台 SMTP 测试成功"
        text_body = (
            "这是一封测试邮件。\n"
            f"账号：{username}\n"
            "如果你收到这封邮件，说明 SMTP 配置可用。"
        )
        html_body = (
            "<html><body style='font-family:Arial,sans-serif;'>"
            "<h2>SMTP 测试成功</h2>"
            f"<p>账号：<b>{username}</b></p>"
            "<p>如果你收到这封邮件，说明 SMTP 配置可用。</p>"
            "</body></html>"
        )
        await self.send_email(smtp_cfg=smtp_cfg, to_emails=[to_email], subject=subject, text_body=text_body, html_body=html_body)

    async def send_email(
        self,
        *,
        smtp_cfg: dict[str, object],
        to_emails: list[str],
        subject: str,
        text_body: str,
        html_body: str,
    ) -> None:
        await asyncio.to_thread(
            _send_email_sync,
            smtp_cfg,
            to_emails,
            subject,
            text_body,
            html_body,
        )


def _send_email_sync(
    smtp_cfg: dict[str, object],
    to_emails: list[str],
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    smtp_host = str(smtp_cfg.get("smtp_host") or "").strip()
    smtp_port = int(smtp_cfg.get("smtp_port") or 587)
    use_tls = bool(smtp_cfg.get("use_tls", True))
    use_ssl = bool(smtp_cfg.get("use_ssl", False))
    username = str(smtp_cfg.get("username") or "").strip()
    password = str(smtp_cfg.get("password") or "").strip()
    from_addr = str(smtp_cfg.get("from") or username).strip()
    timeout_s = int(smtp_cfg.get("timeout_s") or 30)

    if not smtp_host:
        raise ValueError("smtp_host 不能为空")
    if not from_addr:
        raise ValueError("from_email 不能为空")
    recipients = [item.strip() for item in to_emails if item and item.strip()]
    if not recipients:
        raise ValueError("to_emails 不能为空")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8").encode()
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(smtp_host, smtp_port, timeout=timeout_s) as server:
        server.ehlo()
        if use_tls and not use_ssl:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if username:
            server.login(username, password)
        server.sendmail(from_addr, recipients, msg.as_string())

