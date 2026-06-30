import secrets
from soar.workflows.base import WebhookWorkflow
from soar.connectors import connectors
from soar.logger import get_logger

_log = get_logger("workflow.WebhookToFile")


class WebhookToFile(WebhookWorkflow):
    path = "/webhook/to-file"
    token = secrets.token_urlsafe(32)

    def run(self, context):
        payload = context.get("payload", {})
        connectors.file_logs.write_json("webhook_events.jsonl", payload)
        connectors.file_logs.append(
            "webhook_events.jsonl",
            "\n"
        )
        _log.info(f"Webhook payload written to file")
        return {"status": "saved", "payload": payload}
