"""Email notification channel via SMTP."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


class EmailChannel:
    """Send notifications via SMTP. Runs smtplib in a thread to avoid blocking."""

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "",
        use_tls: bool = True,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address or smtp_user
        self.use_tls = use_tls

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        html: Optional[str] = None,
    ) -> bool:
        """Send an email asynchronously (offloads blocking SMTP to a thread)."""
        if not self.smtp_host:
            logger.warning("EmailChannel: no smtp_host configured")
            return False

        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._send_sync, to, subject, body, html)

    def _send_sync(self, to: str, subject: str, body: str, html: Optional[str]) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_address
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            if html:
                msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_user:
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_address, [to], msg.as_string())
            return True
        except Exception as exc:
            logger.warning("Email send failed: %s", exc)
            return False
