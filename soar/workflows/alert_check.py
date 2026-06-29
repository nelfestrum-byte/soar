from soar.workflows.base import ScheduledWorkflow
from soar.connectors import connectors


class MyAlertCheck(ScheduledWorkflow):
    schedule = "*/10 * * * *"

    def run(self, context):
        alerts = connectors.elastic1.query("alerts", {"query": {"match_all": {}}})
        for alert in alerts:
            self._logger.info(f"Alert: {alert}")
        return {"alerts_count": len(alerts)}
