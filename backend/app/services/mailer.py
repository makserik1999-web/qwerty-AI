"""Sending email: account confirmation and password reset.

Two transports. "log" prints the message to the backend log - that is how
development works, and how a server runs before it has a mail account. "smtp"
hands it to any provider over SMTP with the standard library, so changing
provider is a change of four settings, not of code.

`send` never raises. A message that did not go out is logged and reported as
False; the caller decides whether the person needs to hear about it. A signup
must not fail because the mail server was slow.

Every message is in Kazakh and Russian: the server does not know which one
the reader uses, and both are short.
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Optional, Set

from app import config

SMTP_TIMEOUT_SEC = 20

# Background sends, kept so they are not garbage-collected mid-flight.
_pending: Set[asyncio.Task] = set()


def _smtp_send(message: EmailMessage) -> None:
    if config.SMTP_SECURITY == "ssl":
        server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=SMTP_TIMEOUT_SEC,
                                  context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=SMTP_TIMEOUT_SEC)
    with server:
        if config.SMTP_SECURITY == "starttls":
            server.starttls(context=ssl.create_default_context())
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(message)


def _build(to: str, subject: str, text: str, html: Optional[str]) -> EmailMessage:
    message = EmailMessage()
    message["From"] = config.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    domain = config.SMTP_FROM.rsplit("@", 1)[-1].strip(" >") or "localhost"
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


async def send(to: str, subject: str, text: str, html: Optional[str] = None) -> bool:
    if config.MAIL_TRANSPORT != "smtp":
        print(f"[mail] transport=log to={to} subject={subject}\n{text}", flush=True)
        return True
    if not config.SMTP_HOST:
        print("[mail] MAIL_TRANSPORT=smtp but SMTP_HOST is empty - not sent", flush=True)
        return False
    try:
        await asyncio.to_thread(_smtp_send, _build(to, subject, text, html))
        return True
    except Exception as e:  # noqa: BLE001 - reported, never raised
        print(f"[mail] send to {to} failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return False


def send_later(to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    """Send without making the request wait for the mail server."""
    task = asyncio.create_task(send(to, subject, text, html))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


# ------------------------------------------------------------------ messages --


def _html(paragraphs: list, link: str, button: str) -> str:
    body = "".join(f'<p style="margin:0 0 12px">{p}</p>' for p in paragraphs)
    return (
        '<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.5;color:#14203a">'
        f"{body}"
        f'<p style="margin:20px 0"><a href="{link}" style="background:#1f6feb;color:#fff;'
        f'padding:10px 18px;border-radius:8px;text-decoration:none">{button}</a></p>'
        f'<p style="margin:0;color:#5a6880;font-size:13px">{link}</p>'
        "</div>"
    )


def verification_message(link: str) -> tuple:
    subject = "Akron: поштаны растаңыз / подтвердите почту"
    text = (
        "Сәлеметсіз бе! Akron аккаунтыңыздың поштасын растау үшін сілтемені ашыңыз:\n"
        f"{link}\n\n"
        "Здравствуйте! Чтобы подтвердить почту аккаунта Akron, откройте ссылку:\n"
        f"{link}\n\n"
        "Егер сіз тіркелмесеңіз, бұл хатты елемеңіз. / "
        "Если вы не регистрировались, просто проигнорируйте письмо."
    )
    html = _html(
        ["Akron аккаунтыңыздың поштасын растаңыз.", "Подтвердите почту аккаунта Akron."],
        link, "Растау / Подтвердить",
    )
    return subject, text, html


def reset_message(link: str, minutes: int) -> tuple:
    subject = "Akron: құпия сөзді қалпына келтіру / сброс пароля"
    text = (
        f"Жаңа құпия сөз орнату үшін сілтемені ашыңыз ({minutes} минут жарамды):\n{link}\n\n"
        f"Чтобы задать новый пароль, откройте ссылку (действует {minutes} минут):\n{link}\n\n"
        "Егер сіз сұрамасаңыз, ештеңе істемеңіз — құпия сөз өзгермейді. / "
        "Если вы не запрашивали сброс, ничего не делайте: пароль не изменится."
    )
    html = _html(
        [f"Жаңа құпия сөз орнату үшін басыңыз ({minutes} минут).",
         f"Нажмите, чтобы задать новый пароль ({minutes} минут)."],
        link, "Құпия сөзді өзгерту / Сменить пароль",
    )
    return subject, text, html
