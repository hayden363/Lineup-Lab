"""
OUTBOUND MAIL — Gmail SMTP
============================
Sends the two emails this app sends: "verify your account" and
"reset your password." Uses Gmail's SMTP relay with an App Password (not
your real Gmail password — a 16-character app-specific one you generate
once).

IMPORTANT — whose email address this is: `GMAIL_ADDRESS` below is YOUR
Gmail account (or any address you control) — Lineup Lab sends through it,
the same way any app sends through a mail account someone owns. There's no
"Claude-owned" inbox this could send from or reply from instead: an AI
assistant has no persistent email inbox to check or respond from, in this
conversation or any other. Mail always goes out under an address you
control, and only you receive replies to it.

Credentials are read from environment variables, loaded from a local
`.env` file (gitignored — never commit it). This file sets them:

    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=your16charapppassword

How to generate an App Password:
  1. Turn on 2-Step Verification: https://myaccount.google.com/security
  2. Create an App Password: https://myaccount.google.com/apppasswords
     (name it anything, e.g. "Lineup Lab") — Google shows it once.
  3. Put it in `.env` as shown above (see `.env.example`).

If `.env` isn't set up, signup/forgot-password still work — accounts just
stay unverified / reset links don't go out, and the send functions raise
`MailNotConfigured`, which callers log and swallow rather than failing
the request.
"""

import os
import smtplib
from email.message import EmailMessage

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars can still be set another way

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")


class MailNotConfigured(Exception):
    pass


class MailSendError(Exception):
    pass


def configured():
    return bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)


def _send(to_email, subject, text_body, html_body):
    if not configured():
        raise MailNotConfigured(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set — see engine/mail.py or .env.example"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Lineup Lab <{GMAIL_ADDRESS}>"
    msg["To"] = to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailSendError(
            "Gmail rejected the login — check GMAIL_ADDRESS/GMAIL_APP_PASSWORD in .env "
            "(must be an App Password, not your normal Gmail password)."
        ) from e
    except Exception as e:
        raise MailSendError(f"Couldn't send email: {e}") from e


# A plain, high-contrast, light template — deliberately simple rather than
# on-brand-dark: dark-background HTML renders inconsistently across mail
# clients (Outlook desktop especially), so transactional email conventions
# favor a plain white card. Professional and easy to read beats on-brand.
# The polish below (gradient top bar, weightier type, a glow-halo button)
# stays inside that constraint — no dark body background, no client-fragile
# CSS (flexbox/grid/custom fonts) — just a sharper version of the same card.
def _wrap(title, body_html, footer_note):
    return f"""\
<div style="background:#eef2f0;padding:40px 16px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
  <div style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:14px;
              overflow:hidden;border:1px solid #e2e8e4;box-shadow:0 4px 24px rgba(18,32,26,0.06);">
    <div style="height:5px;background:linear-gradient(90deg,#1f6f52,#5eeead);"></div>
    <div style="padding:36px 32px 32px;">
      <div style="display:flex;align-items:center;gap:8px;font-size:15px;font-weight:800;
                  color:#1f6f52;letter-spacing:0.02em;margin-bottom:24px;">
        <span style="font-size:18px;">🏈</span>LINEUP LAB
      </div>
      <h1 style="font-size:21px;margin:0 0 16px;color:#0e1b15;font-weight:800;">{title}</h1>
      {body_html}
      <p style="color:#8a988f;font-size:12px;margin-top:32px;padding-top:16px;
                border-top:1px solid #eef1ef;line-height:1.6;">
        {footer_note}
      </p>
    </div>
  </div>
  <p style="max-width:480px;margin:20px auto 0;text-align:center;color:#a3afa8;font-size:11px;">
    Lineup Lab — a fantasy football valuation tool.
  </p>
</div>"""


def _button(url, label):
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin:26px 0;">
      <tr><td style="border-radius:9px;background:#1f6f52;box-shadow:0 6px 18px -4px rgba(31,111,82,0.45);">
        <a href="{url}" style="background:#1f6f52;color:#ffffff;padding:13px 28px;border-radius:9px;
           text-decoration:none;font-weight:700;font-size:14px;display:inline-block;">
          {label}
        </a>
      </td></tr>
    </table>
    <p style="color:#8a988f;font-size:12px;word-break:break-all;line-height:1.5;">
      Or paste this link into your browser:<br>
      <span style="color:#4a5a52;">{url}</span>
    </p>"""


def send_verification_email(to_email, username, verify_url):
    subject = "Verify your Lineup Lab account"
    text = (
        f"Hi {username},\n\n"
        f"Confirm this is your email to finish setting up your Lineup Lab account:\n\n"
        f"{verify_url}\n\n"
        f"This link expires in 24 hours. If you didn't create this account, you can ignore this email — "
        f"no changes will be made.\n"
    )
    body = f"""
      <p style="color:#3c4a44;font-size:14px;line-height:1.6;">
        Hi {username}, thanks for creating a Lineup Lab account. Click below to confirm this
        is your email address.
      </p>
      {_button(verify_url, "Verify Email")}
    """
    html = _wrap(
        "Confirm your email",
        body,
        "This link expires in 24 hours. If you didn't create this account, you can safely ignore this email — no changes will be made.",
    )
    _send(to_email, subject, text, html)


def send_password_reset_email(to_email, username, reset_url):
    subject = "Reset your Lineup Lab password"
    text = (
        f"Hi {username},\n\n"
        f"We received a request to reset your Lineup Lab password. Click the link below to choose a new one:\n\n"
        f"{reset_url}\n\n"
        f"This link expires in 1 hour and can only be used once. If you didn't request this, "
        f"you can ignore this email — your password won't change.\n"
    )
    body = f"""
      <p style="color:#3c4a44;font-size:14px;line-height:1.6;">
        Hi {username}, we received a request to reset your Lineup Lab password. Click below to choose a new one.
      </p>
      {_button(reset_url, "Reset Password")}
    """
    html = _wrap(
        "Reset your password",
        body,
        "This link expires in 1 hour and works once. If you didn't request this, you can safely ignore this email — your password stays the same.",
    )
    _send(to_email, subject, text, html)
