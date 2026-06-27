import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from alerts.health import Alert

log = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, config: dict) -> None:
        self._cfg = config["email"]
        self._from = os.environ["FROM_EMAIL"]
        self._to = [addr.strip() for addr in os.environ["TO_EMAILS"].split(",")]

    def send(self, alerts: list[Alert]) -> None:
        cats = sorted({a.cat.title() for a in alerts})
        subject = f"[SuPurrMente] {len(alerts)} alerta(s) — {', '.join(cats)}"
        body = self._format_body(alerts)

        msg = MIMEMultipart()
        msg["From"] = self._from
        msg["To"] = ", ".join(self._to)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        password = os.environ["GMAIL_APP_PASSWORD"]
        with smtplib.SMTP(self._cfg["smtp_host"], self._cfg["smtp_port"]) as smtp:
            smtp.starttls()
            smtp.login(self._from, password)
            smtp.sendmail(self._from, self._to, msg.as_string())

        log.info("Email de alertas enviado: %s", subject)

    def _format_body(self, alerts: list[Alert]) -> str:
        lines = ["SuPurrMente — Informe de salud", "=" * 32, ""]
        for a in sorted(alerts, key=lambda x: (x.cat, x.severity)):
            lines.append(f"[{a.severity.upper()}] {a.message}")
        return "\n".join(lines)
