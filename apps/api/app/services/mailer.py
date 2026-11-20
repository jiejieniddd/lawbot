from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from app.services.mail_config import MailConfig


class MailDeliveryError(Exception):
    pass


def send_email(config: MailConfig, to: str, subject: str, text: str) -> None:
    if not config.smtp_host or not config.from_address:
        raise MailDeliveryError("邮件服务未配置完整")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config.from_name or "", config.from_address))
    message["To"] = to
    message.set_content(text)
    try:
        if config.smtp_security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=20)
        else:
            client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20)
        with client as smtp:
            smtp.ehlo()
            if config.smtp_security == "starttls":
                smtp.starttls()
                smtp.ehlo()
            if config.smtp_username:
                smtp.login(config.smtp_username, config.smtp_password)
            smtp.send_message(message)
    except MailDeliveryError:
        raise
    except Exception as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        secret = config.smtp_password or ""
        if secret and secret in reason:
            reason = reason.replace(secret, "****")
        raise MailDeliveryError(f"邮件发送失败：{reason}") from exc
