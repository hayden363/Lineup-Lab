"""
OUTBOUND MAIL — Resend (preferred) or Gmail SMTP
================================================
Sends the four emails this app sends: "verify your account", "reset your
password", a welcome message once an account is confirmed, and a "your password
was changed" security notice.

Two ways to send; if both are configured Resend is tried first and Gmail is
the fallback:

  Resend   RESEND_API_KEY + MAIL_FROM (e.g. "Lineup Lab <hello@yourdomain.com>").
           Sends from an address on a domain you verify with Resend (SPF/DKIM),
           so it looks like Lineup Lab and lands in inboxes far more reliably.
           MAIL_REPLY_TO is optional (where replies should go).
  Gmail    GMAIL_ADDRESS + an App Password (below). Fine for a handful of
           people; consumer Gmail caps sends at a few hundred a day.

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
import time
import requests
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from urllib.parse import urlsplit

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars can still be set another way

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
MAIL_FROM = os.environ.get("MAIL_FROM")          # required with Resend, e.g. "Lineup Lab <hello@example.com>"
MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO")  # optional
RESEND_URL = "https://api.resend.com/emails"
_RESEND_TIMEOUT = 10


class MailNotConfigured(Exception):
    pass


class MailSendError(Exception):
    pass


def gmail_configured():
    return bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)


def resend_configured():
    return bool(RESEND_API_KEY and MAIL_FROM)


def configured():
    return resend_configured() or gmail_configured()


def _send_resend(to_email, subject, text_body, html_body):
    payload = {"from": MAIL_FROM, "to": [to_email], "subject": subject, "text": text_body, "html": html_body,
               "headers": {"Auto-Submitted": "auto-generated"}}
    if MAIL_REPLY_TO:
        payload["reply_to"] = MAIL_REPLY_TO
    try:
        r = requests.post(RESEND_URL, json=payload, timeout=_RESEND_TIMEOUT,
                          headers={"Authorization": f"Bearer {RESEND_API_KEY}", "User-Agent": "LineupLab/1.0"})
    except requests.RequestException as e:
        raise MailSendError(f"Resend unreachable: {type(e).__name__}: {e}") from e
    if r.status_code >= 300:
        try:
            detail = (r.json() or {}).get("message") or r.text[:200]
        except ValueError:
            detail = r.text[:200]
        raise MailSendError(f"Resend rejected the email ({r.status_code}): {detail}")


def _send(to_email, subject, text_body, html_body):
    """Resend first when configured, Gmail otherwise or as the fallback. With a
    single provider its own error is raised unchanged."""
    senders = []
    if resend_configured():
        senders.append(_send_resend)
    if gmail_configured():
        senders.append(_send_gmail)
    if not senders:
        raise MailNotConfigured(
            "No mail provider set — RESEND_API_KEY + MAIL_FROM, or GMAIL_ADDRESS + GMAIL_APP_PASSWORD "
            "(see engine/mail.py or .env.example)"
        )
    errors = []
    for i, send in enumerate(senders):
        try:
            send(to_email, subject, text_body, html_body)
            return
        except MailSendError as e:
            errors.append(str(e))
            if i < len(senders) - 1:
                print(f"[mail] {getattr(send, '__name__', 'provider')} failed, trying the next provider: {e}")
    if len(errors) == 1:
        raise MailSendError(errors[0])
    raise MailSendError(" | ".join(errors))


def _send_gmail(to_email, subject, text_body, html_body):
    # configured() guarantees both are set, but that's invisible to pyright
    # across the function-call boundary — spell it out so smtp.login() below
    # type-checks as the non-Optional strs they actually are here.
    assert GMAIL_ADDRESS is not None and GMAIL_APP_PASSWORD is not None

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Lineup Lab <{GMAIL_ADDRESS}>"
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=GMAIL_ADDRESS.rsplit("@", 1)[-1])
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    failures = []
    for port, implicit_tls in _SMTP_ATTEMPTS:
        try:
            _smtp_attempt(port, implicit_tls, msg)
            return
        except smtplib.SMTPAuthenticationError as e:
            # Reached Gmail and it said no — the other port would say the same.
            raise MailSendError(
                "Gmail rejected the login — check GMAIL_ADDRESS/GMAIL_APP_PASSWORD in .env "
                "(must be an App Password, not your normal Gmail password)."
            ) from e
        except _SmtpStepError as e:
            failures.append(str(e))
    raise MailSendError("Couldn't send email — " + "; ".join(failures))


class _SmtpStepError(Exception):
    pass


SMTP_HOST = "smtp.gmail.com"
# (port, implicit TLS). Render's outbound SMTP rules differ by plan and by port
# (free plan blocks 25/465/587 outright), and the failure from inside the app
# looks the same whichever layer drops the connection, so try both Gmail ports
# and report exactly which step of which one failed instead of one opaque
# "Connection unexpectedly closed". 10s each so a fully blocked host still
# answers the user's request in ~20s, not longer.
_SMTP_ATTEMPTS = ((587, False), (465, True))
_SMTP_TIMEOUT = 10


def _smtp_attempt(port, implicit_tls, msg):
    assert GMAIL_ADDRESS is not None and GMAIL_APP_PASSWORD is not None
    step = "connect"
    try:
        smtp = (smtplib.SMTP_SSL(SMTP_HOST, port, timeout=_SMTP_TIMEOUT) if implicit_tls
                else smtplib.SMTP(SMTP_HOST, port, timeout=_SMTP_TIMEOUT))
        with smtp:
            if not implicit_tls:
                step = "starttls"
                smtp.starttls()
            step = "login"
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            step = "send"
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise
    except Exception as e:
        raise _SmtpStepError(f"port {port} failed at {step}: {type(e).__name__}: {e}") from e


# A plain, high-contrast, light template — deliberately simple rather than
# on-brand-dark: dark-background HTML renders inconsistently across mail
# clients (Outlook desktop especially), so transactional email conventions
# favor a plain white card. It is table-based with inline styles for the same
# reason (flexbox/grid/custom fonts are the fragile bits). The logo is the app
# icon served from the app's own host: mail clients block data: URIs and SVG,
# so it has to be a normal PNG at an absolute https URL.
_BRAND_GREEN = "#1f6f52"
_BRAND_DARK = "#0f3d2e"


def _origin(url):
    """https://host from any absolute URL we're already emailing a link to, so
    the logo always comes from the same host as the link (prod or a preview)."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _wrap(title, body_html, footer_note, origin):
    logo = f"{origin}/icons/email-logo.png"
    return f"""\
<div style="background:#eef2f0;padding:32px 12px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;">
    <tr><td style="background:{_BRAND_DARK};border-radius:14px 14px 0 0;padding:22px 32px;">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="padding-right:12px;vertical-align:middle;">
          <img src="{logo}" width="44" height="44" alt="Lineup Lab"
               style="display:block;border:0;border-radius:10px;">
        </td>
        <td style="vertical-align:middle;color:#ffffff;font-size:18px;font-weight:800;letter-spacing:0.04em;">
          LINEUP LAB
          <div style="color:#8fd9b8;font-size:11px;font-weight:600;letter-spacing:0.06em;margin-top:2px;">
            FANTASY FOOTBALL VALUATION
          </div>
        </td>
      </tr></table>
    </td></tr>
    <tr><td style="height:4px;background:linear-gradient(90deg,#1f6f52,#5eeead);font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="background:#ffffff;border:1px solid #e2e8e4;border-top:0;border-radius:0 0 14px 14px;padding:32px;">
      <h1 style="font-size:21px;margin:0 0 16px;color:#0e1b15;font-weight:800;">{title}</h1>
      {body_html}
      <p style="color:#8a988f;font-size:12px;margin:32px 0 0;padding-top:16px;
                border-top:1px solid #eef1ef;line-height:1.6;">
        {footer_note}
      </p>
      <p style="color:#8a988f;font-size:12px;margin:12px 0 0;line-height:1.6;">
        <strong style="color:#4a5a52;">Can't find our emails?</strong> Check your spam or junk
        folder. If this one landed there, mark it <em>Not spam</em> so future emails reach your inbox.
      </p>
    </td></tr>
  </table>
  <p style="max-width:520px;margin:18px auto 0;text-align:center;color:#a3afa8;font-size:11px;line-height:1.5;">
    You're getting this because someone used this address on Lineup Lab.<br>
    <a href="{origin}" style="color:#a3afa8;">{origin.split("://", 1)[-1]}</a>
  </p>
</div>"""


def _button(url, label):
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin:26px 0;">
      <tr><td style="border-radius:9px;background:{_BRAND_GREEN};">
        <a href="{url}" style="background:{_BRAND_GREEN};color:#ffffff;padding:14px 30px;border-radius:9px;
           text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">
          {label}
        </a>
      </td></tr>
    </table>
    <p style="color:#8a988f;font-size:12px;word-break:break-all;line-height:1.5;">
      Button not working? Paste this link into your browser:<br>
      <span style="color:#4a5a52;">{url}</span>
    </p>"""


def send_verification_email(to_email, username, verify_url):
    subject = "Verify your Lineup Lab account"
    text = (
        f"Hi {username},\n\n"
        f"Confirm this is your email to finish setting up your Lineup Lab account:\n\n"
        f"{verify_url}\n\n"
        f"This link expires in 24 hours. If you didn't create this account, you can ignore this email — "
        f"no changes will be made.\n\n"
        f"Can't find our emails? Check your spam or junk folder, and mark this one 'Not spam'.\n"
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
        _origin(verify_url),
    )
    _send(to_email, subject, text, html)


def send_password_reset_email(to_email, username, reset_url):
    subject = "Reset your Lineup Lab password"
    text = (
        f"Hi {username},\n\n"
        f"We received a request to reset your Lineup Lab password. Click the link below to choose a new one:\n\n"
        f"{reset_url}\n\n"
        f"This link expires in 1 hour and can only be used once. If you didn't request this, "
        f"you can ignore this email — your password won't change.\n\n"
        f"Can't find our emails? Check your spam or junk folder, and mark this one 'Not spam'.\n"
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
        _origin(reset_url),
    )
    _send(to_email, subject, text, html)


def send_welcome_email(to_email, username, app_url):
    """Sent once, when an account's email is confirmed (or a Google sign-up
    creates a pre-confirmed account). `app_url` is any absolute URL on the app's
    own host; the logo and the button both come from that host."""
    origin = _origin(app_url)
    subject = "Welcome to Lineup Lab"
    text = (
        f"Hi {username},\n\n"
        f"Welcome to Lineup Lab. A few good places to start:\n\n"
        f"- Big Board: every QB, RB, WR and TE on one list, ranked by Player Value Score (0-100), "
        f"the points a player gives your lineup over a free replacement.\n"
        f"- Settings: connect your Sleeper or ESPN league so My Team, Waivers, Start/Sit and the "
        f"trade finder use your real roster and scoring.\n"
        f"- Start/Sit and Waivers: who to play this week and who to pick up.\n\n"
        f"Open Lineup Lab: {origin}\n\n"
        f"Questions or something looks wrong? Just reply to this email.\n"
    )
    body = f"""
      <p style="color:#3c4a44;font-size:14px;line-height:1.6;">
        Hi {username}, welcome to Lineup Lab. A few good places to start:
      </p>
      <ul style="color:#3c4a44;font-size:14px;line-height:1.7;padding-left:20px;margin:0 0 4px;">
        <li><strong>Big Board</strong> &mdash; every QB, RB, WR and TE on one list, ranked by
            Player Value Score (0&ndash;100): the points a player gives your lineup over a free replacement.</li>
        <li><strong>Settings</strong> &mdash; connect your Sleeper or ESPN league so My Team, Waivers,
            Start/Sit and the trade finder use your real roster and scoring.</li>
        <li><strong>Start/Sit and Waivers</strong> &mdash; who to play this week and who to pick up.</li>
      </ul>
      {_button(origin, "Open Lineup Lab")}
    """
    html = _wrap(
        "Welcome to Lineup Lab",
        body,
        "Questions, or something looks wrong? Just reply to this email.",
        origin,
    )
    _send(to_email, subject, text, html)


def send_password_changed_email(to_email, username, app_url, when=None):
    """Security notice after a password change or reset. Says when, and what to
    do if it wasn't the account owner. Never contains the password or a link
    that logs anyone in."""
    origin = _origin(app_url)
    stamp = time.strftime("%B %d, %Y at %H:%M UTC", time.gmtime(when if when is not None else time.time()))
    subject = "Your Lineup Lab password was changed"
    text = (
        f"Hi {username},\n\n"
        f"The password on your Lineup Lab account was changed on {stamp}.\n\n"
        f"If that was you, there's nothing more to do.\n\n"
        f"If it wasn't you, reset your password right away: open {origin}, choose Sign in, then "
        f"\"Forgot password\", and use the link we email you. Then reply to this email so we know.\n"
    )
    body = f"""
      <p style="color:#3c4a44;font-size:14px;line-height:1.6;">
        Hi {username}, the password on your Lineup Lab account was changed on <strong>{stamp}</strong>.
      </p>
      <p style="color:#3c4a44;font-size:14px;line-height:1.6;">
        If that was you, there's nothing more to do.
      </p>
      <p style="color:#3c4a44;font-size:14px;line-height:1.6;">
        <strong>If it wasn't you</strong>, reset your password right away: open Lineup Lab, choose
        <em>Sign in</em>, then <em>Forgot password</em>, and use the link we email you. Then reply to this
        email so we know.
      </p>
      {_button(origin, "Open Lineup Lab")}
    """
    html = _wrap(
        "Your password was changed",
        body,
        "We send this notice every time a password changes so a change you didn't make never goes unnoticed.",
        origin,
    )
    _send(to_email, subject, text, html)
