from soar.connectors import connectors
from soar.workflows.base import ScheduledWorkflow


class MyAlertCheck(ScheduledWorkflow):
    schedule = "*/10 * * * *"

    def run(self, context):
        alerts = connectors.elastic1.query("alerts", {"query": {"match_all": {}}})  # type: ignore[attr-defined]
        for alert in alerts:
            self._logger.info(f"Alert: {alert}")  # type: ignore[attr-defined]
        return {"alerts_count": len(alerts)}
