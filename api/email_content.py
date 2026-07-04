"""Pure renderers for the two transactional emails Praxys sends.

No I/O here — each function returns ``(subject, text_body, html_body)`` and the
caller hands that to :func:`api.email_sender.send_email`. Emails are bilingual
(English + 简体中文) because the CN audience is primary and we usually don't
know the recipient's locale at send time; ``locale`` only reorders which
language leads.

Link building is centralized here so every outbound link uses the same
``PRAXYS_APP_BASE_URL`` (default https://praxys.run).
"""
from __future__ import annotations

import os
from urllib.parse import quote

DEFAULT_APP_BASE_URL = "https://praxys.run"


def app_base_url() -> str:
    """Public origin used to build verify / invite links (no trailing slash)."""
    raw = os.environ.get("PRAXYS_APP_BASE_URL") or DEFAULT_APP_BASE_URL
    return raw.rstrip("/")


def verify_url(token: str) -> str:
    return f"{app_base_url()}/verify?token={quote(token, safe='')}"


def invite_url(code: str) -> str:
    # Deep-links to the login page's invitation-code path (Login.tsx reads
    # ?invite= and prefills the code field).
    return f"{app_base_url()}/login?invite={quote(code, safe='')}"


def _lead_zh(locale: str | None) -> bool:
    return bool(locale) and str(locale).lower().startswith("zh")


def verification_email(token: str) -> tuple[str, str, str]:
    """Email-ownership verification for open self-registration."""
    url = verify_url(token)
    subject = "Verify your Praxys email / 验证你的 Praxys 邮箱"
    text = (
        "Welcome to Praxys!\n\n"
        "Please confirm this email address to activate your account:\n"
        f"{url}\n\n"
        "If you didn't create a Praxys account, you can ignore this email.\n\n"
        "————\n\n"
        "欢迎使用 Praxys！\n\n"
        "请点击以下链接确认邮箱并激活你的账户：\n"
        f"{url}\n\n"
        "如果你没有注册 Praxys 账户，请忽略此邮件。\n"
    )
    html = (
        f'<p>Welcome to Praxys!</p>'
        f'<p>Please confirm this email address to activate your account:</p>'
        f'<p><a href="{url}">Verify my email</a></p>'
        f"<p style=\"color:#666;font-size:13px\">If you didn't create a Praxys "
        f"account, you can ignore this email.</p>"
        f'<hr>'
        f'<p>欢迎使用 Praxys！</p>'
        f'<p>请点击下面的按钮确认邮箱并激活你的账户：</p>'
        f'<p><a href="{url}">验证我的邮箱</a></p>'
        f'<p style="color:#666;font-size:13px">如果你没有注册 Praxys 账户，请忽略此邮件。</p>'
    )
    return subject, text, html


def invitation_email(
    code: str,
    expires_days: int | None = None,
    locale: str | None = None,
) -> tuple[str, str, str]:
    """Invitation-code email for a waitlist signup we're inviting in."""
    url = invite_url(code)
    expiry_en = (
        f"This code expires in {expires_days} days.\n" if expires_days else ""
    )
    expiry_zh = (
        f"该邀请码将在 {expires_days} 天后过期。\n" if expires_days else ""
    )
    en_block = (
        "You're off the Praxys waitlist — welcome in!\n\n"
        f"Your invitation code is: {code}\n\n"
        f"Finish creating your account here:\n{url}\n\n"
        f"{expiry_en}"
        "The link pre-fills your code; you'll just set a password.\n"
    )
    zh_block = (
        "你已从 Praxys 等候名单中获得邀请，欢迎加入！\n\n"
        f"你的邀请码是：{code}\n\n"
        f"点击以下链接完成账户注册：\n{url}\n\n"
        f"{expiry_zh}"
        "链接会自动填入邀请码，你只需设置密码即可。\n"
    )
    subject = "Your Praxys invitation code / 你的 Praxys 邀请码"
    if _lead_zh(locale):
        text = zh_block + "\n————\n\n" + en_block
    else:
        text = en_block + "\n————\n\n" + zh_block

    html_en = (
        f"<p>You're off the Praxys waitlist — welcome in!</p>"
        f"<p>Your invitation code is: <strong>{code}</strong></p>"
        f'<p><a href="{url}">Finish creating your account</a></p>'
        + (f"<p style=\"color:#666;font-size:13px\">This code expires in {expires_days} days.</p>" if expires_days else "")
    )
    html_zh = (
        f"<p>你已从 Praxys 等候名单中获得邀请，欢迎加入！</p>"
        f"<p>你的邀请码是：<strong>{code}</strong></p>"
        f'<p><a href="{url}">完成账户注册</a></p>'
        + (f'<p style="color:#666;font-size:13px">该邀请码将在 {expires_days} 天后过期。</p>' if expires_days else "")
    )
    html = (html_zh + "<hr>" + html_en) if _lead_zh(locale) else (html_en + "<hr>" + html_zh)
    return subject, text, html