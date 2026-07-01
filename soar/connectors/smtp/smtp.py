import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from soar.connectors.base import BaseConnector


class SMTPConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        from_address: str = "",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.from_address = from_address
        self._server: smtplib.SMTP | smtplib.SMTP_SSL | None = None

    def _connect_impl(self):
        if self.use_ssl:
            self._server = smtplib.SMTP_SSL(self.host, self.port)
        else:
            self._server = smtplib.SMTP(self.host, self.port)
            if self.use_tls:
                self._server.starttls()
        if self.username and self.password:
            self._server.login(self.username, self.password)

    def disconnect(self):
        if self._server:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _build_message(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        html: bool = False,
        attachments: list[dict] | None = None,
    ) -> MIMEMultipart:
        recipients = [to] if isinstance(to, str) else to
        msg = MIMEMultipart()
        msg["From"] = self.from_address
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))
        for att in attachments or []:
            with open(att["path"], "rb") as f:
                part = MIMEApplication(f.read(), Name=att.get("name", att["path"].split("/")[-1]))
            part["Content-Disposition"] = f'attachment; filename="{att.get("name", att["path"].split("/")[-1])}"'
            msg.attach(part)
        return msg

    def _send(self, msg: MIMEMultipart) -> dict:
        self._ensure_connected()
        assert self._server is not None
        recipients = msg["To"].split(", ")
        self._server.sendmail(self.from_address, recipients, msg.as_string())
        return {"status": "sent", "recipients": recipients}

    def send_email(self, to: str | list[str], subject: str, body: str, html: bool = False, attachments: list[dict] | None = None) -> dict:
        msg = self._build_message(to, subject, body, html, attachments)
        return self._send(msg)

    def send_text(self, to: str | list[str], subject: str, body: str) -> dict:
        return self.send_email(to, subject, body, html=False)

    def send_html(self, to: str | list[str], subject: str, html: str) -> dict:
        return self.send_email(to, subject, html, html=True)
