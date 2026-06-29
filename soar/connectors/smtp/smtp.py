from soar.connectors.base import BaseConnector


class SmtpConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        from_email: str = "",
        from_name: str = "SOAR",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_email = from_email
        self.from_name = from_name
        self._server = None

    def _connect_impl(self):
        import smtplib
        self._server = smtplib.SMTP(self.host, self.port, timeout=10)
        self._server.ehlo()
        if self.use_tls:
            self._server.starttls()
            self._server.ehlo()
        if self.username and self.password:
            self._server.login(self.username, self.password)
        self._connected = True

    def disconnect(self):
        if self._server:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None
        self._connected = False
        self._logger.info(f"Disconnected from {self.instance_name}")

    def send_email(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        html: bool = False,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        self._ensure_connected()
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        if isinstance(to, str):
            to = [to]
        if isinstance(cc, str):
            cc = [cc]
        if isinstance(bcc, str):
            bcc = [bcc]

        msg = MIMEMultipart()
        msg["From"] = f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)

        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        if attachments:
            for att in attachments:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(att["content"])
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{att.get("filename", "file")}"',
                )
                msg.attach(part)

        all_recipients = to + (cc or []) + (bcc or [])
        self._server.sendmail(self.from_email, all_recipients, msg.as_string())
        self._logger.info(f"Email sent to {', '.join(to)}: {subject}")
        return {"status": "sent", "to": to, "subject": subject}

    def send_text(self, to: str | list[str], subject: str, body: str) -> dict:
        return self.send_email(to=to, subject=subject, body=body, html=False)

    def send_html(self, to: str | list[str], subject: str, body: str) -> dict:
        return self.send_email(to=to, subject=subject, body=body, html=True)
