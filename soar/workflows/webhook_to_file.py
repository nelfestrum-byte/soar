import secrets

from soar.connectors import connectors
from soar.logger import get_logger
from soar.workflows.base import WebhookWorkflow

_log = get_logger("workflow.WebhookToFile")


class WebhookToFile(WebhookWorkflow):
    path = "/webhook/to-file"
    token = secrets.token_urlsafe(32)

    def run(self, context):
        payload = context.get("payload", {})
        connectors.file_logs.write_json("webhook_events.jsonl", payload)  # type: ignore[attr-defined]
        connectors.file_logs.append(  # type: ignore[attr-defined]
            "webhook_events.jsonl",
            "\n"
        )
        _log.info("Webhook payload written to file")
        return {"status": "saved", "payload": payload}
