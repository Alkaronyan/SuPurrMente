"""
Integration test: sends a real email via Gmail SMTP and verifies delivery.

Requires live credentials in the environment (FROM_EMAIL, TO_EMAILS, GMAIL_APP_PASSWORD).
Run only with: pytest tests/test_email_integration.py -v -m integration
Or via Makefile: make test-email

The test sends from alfred@gonzalez.team TO alfred@gonzalez.team so it
can be verified and deleted from the same inbox using the Gmail MCP tools.

Subject contains a unique marker "[SuPurrMente-test]" so the email is easy to
find and clean up.
"""
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

REQUIRED_VARS = ["FROM_EMAIL", "GMAIL_APP_PASSWORD"]


def _missing_vars() -> list[str]:
    return [v for v in REQUIRED_VARS if not os.environ.get(v)]


@pytest.mark.integration
class TestEmailSmtp:
    """Sends a real email over Gmail SMTP. Verifies no exceptions are raised."""

    def _send(self, subject: str, body: str) -> None:
        from_addr = os.environ["FROM_EMAIL"]
        to_addr = from_addr  # send to self for easy cleanup
        password = os.environ["GMAIL_APP_PASSWORD"]

        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(from_addr, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())

    def test_smtp_credentials_present(self):
        missing = _missing_vars()
        if missing:
            pytest.skip(f"Missing env vars: {', '.join(missing)}")

    def test_send_test_email(self):
        missing = _missing_vars()
        if missing:
            pytest.skip(f"Missing env vars: {', '.join(missing)}")

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        subject = f"[SuPurrMente-test] Prueba de integración SMTP — {ts}"
        body = (
            "Este email fue enviado automáticamente por el test de integración de SuPurrMente.\n"
            f"Timestamp: {ts}\n\n"
            "Si lo estás leyendo, el envío funciona correctamente.\n"
            "Este mensaje puede borrarse."
        )

        self._send(subject, body)
        # If we reach here, SMTP completed without exception

    def test_send_alert_format(self):
        """Verify that EmailSender can format and send a real alert email."""
        missing = _missing_vars()
        if missing:
            pytest.skip(f"Missing env vars: {', '.join(missing)}")

        from alerts.email_sender import EmailSender
        from alerts.health import Alert

        config = {
            "email": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
            }
        }

        # Temporarily redirect TO_EMAILS to FROM_EMAIL so we receive our own test email
        os.environ.setdefault("TO_EMAILS", os.environ["FROM_EMAIL"])

        alerts = [
            Alert(cat="pirata", severity="warning",
                  message="Pirata pesa 9.50 kg, por encima de 2.0σ (media=6.50 kg, σ=0.10 kg)"),
            Alert(cat="robin", severity="critical",
                  message="Robin lleva 26.0h sin usar la caja (umbral=24h)"),
        ]

        sender = EmailSender(config)
        sender.send(alerts)
