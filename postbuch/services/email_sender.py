from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML → plain-text conversion (no external deps)
# ---------------------------------------------------------------------------

class _HTMLStripper(HTMLParser):
    """Minimal HTML→text converter: strips tags, decodes entities, preserves line breaks."""

    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._in_style_script = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("style", "script"):
            self._in_style_script = True
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self._in_style_script = False
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._in_style_script:
            self._parts.append(data)

    def get_text(self) -> str:
        import re
        text = "".join(self._parts)
        # Collapse runs of 3+ newlines → 2 (preserve paragraph breaks)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """Strip HTML tags and return readable plain text."""
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        # If parsing fails for any reason, return the raw HTML as a last resort
        return html


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _extract_body_text(body_text: str, body_html: str | None) -> str:
    """Return best available plain-text body.

    Prefers plain-text; falls back to HTML-stripped version if body_text is
    empty or whitespace-only (common with HTML-only emails).
    """
    if body_text and body_text.strip():
        return body_text
    if body_html:
        return html_to_text(body_html)
    return ""


def _format_quoted_original(
    subject: str,
    sender: str | None,
    received_at: datetime | None,
    body_text: str,
    body_html: str | None,
) -> str:
    """Build the standard 'Weitergeleitete Nachricht' quoted block.

    This is what {inhalt} expands to — the separator header plus the full
    original body (with HTML-to-text fallback), so templates only need to
    write their own preamble and place {inhalt} below it.
    """
    # RFC 2822 date format, matching what email clients display
    datum = received_at.strftime("%a, %d %b %Y %H:%M:%S %z") if received_at else ""
    content = _extract_body_text(body_text, body_html)
    parts = [
        "-------- Weitergeleitete Nachricht --------",
        f"Betreff:\t{subject or ''}",
        f"Datum:\t{datum}",
        f"Von:\t{sender or ''}",
        "",
        "",
        content,
    ]
    return "\n".join(parts)


def render_template(
    template: str,
    subject: str,
    sender: str | None,
    received_at: datetime | None,
    body_text: str,
    body_html: str | None = None,
) -> str:
    """Substitute placeholders in a template string.

    Supported placeholders:
      {betreff}  — original email subject
      {absender} — original sender address
      {datum}    — received_at formatted as dd.mm.yyyy HH:MM (or empty string)
      {inhalt}   — quoted original message block (separator + headers + body)
    """
    datum = received_at.strftime("%d.%m.%Y %H:%M") if received_at else ""
    quoted = _format_quoted_original(subject, sender, received_at, body_text, body_html)

    return (
        template
        .replace("{betreff}", subject or "")
        .replace("{absender}", sender or "")
        .replace("{datum}", datum)
        .replace("{inhalt}", quoted)
    )


def render_default_forward(
    subject: str,
    sender: str | None,
    received_at: datetime | None,
    body_text: str,
    body_html: str | None = None,
) -> tuple[str, str]:
    """Render a plain forward with no custom preamble (used when no template is selected).

    Returns (rendered_subject, rendered_body).
    """
    fwd_subject = f"Weiterleitung: {subject}" if subject else "Weiterleitung"
    fwd_body = _format_quoted_original(subject, sender, received_at, body_text, body_html)
    return fwd_subject, fwd_body


# ---------------------------------------------------------------------------
# SMTP sending
# ---------------------------------------------------------------------------

def send_forward_email(
    to: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str | None,
    smtp_password: str | None,
    smtp_from_address: str | None,
    smtp_use_tls: bool,
) -> bytes:
    """Send a plain-text email via SMTP.

    Returns the raw RFC 2822 message bytes so callers can APPEND it to an
    IMAP sent folder.  Raises ``smtplib.SMTPException`` on failure.
    """
    from_address = smtp_from_address or smtp_username or "postbuch@localhost"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(smtp_from_address or smtp_username or "localhost").split("@")[-1])

    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
        server.ehlo()
        if smtp_use_tls:
            server.starttls()
            server.ehlo()
        if smtp_username:
            server.login(smtp_username, smtp_password or "")
        server.sendmail(from_address, [to], msg.as_string())
    logger.info("Forward email sent to %s (subject: %r)", to, subject)
    return msg.as_bytes()
