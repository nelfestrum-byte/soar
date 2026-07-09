"""First response playbook (contract §6, plan Task 5) — non-destructive.

Goal: prove the end-to-end cycle in the IRP UI. The playbook registers a
guided-response checklist on the alert, comments that SOAR took the alert,
performs the automatic (read-only) steps and marks them done — strictly after
actual execution, never in advance.

Deliberately NOT here:
  - transition_alert — statuses are moved by analysts in the MVP;
  - destructive actions (account/IP block, host isolation) — phase 4 only,
    behind SOC Core's pending-approval UI.
"""

import os

from soar.connectors import connectors
from soar.tools.irp_settings import load_irp_settings
from soar.workflows.base import ManualWorkflow

# Per-rule step texts live in SOC Core's frontend (ruleExplanations.ts) — until
# their export exists (plan assumption Д-4) we ship a minimal local catalog and
# fall back to a generic 3-step checklist for unknown rules.
GENERIC_STEPS = [
    {"text": "SOAR: собрать контекст алерта (автоматически)", "action": "collect_context"},
    {"text": "Проверить активность хоста/учётной записи за последние 24 часа", "action": None},
    {"text": "Принять решение: эскалация в инцидент или закрытие с обоснованием", "action": None},
]

RESPONSE_STEP_CATALOG: dict[str, list[dict]] = {}


class BasicResponseWorkflow(ManualWorkflow):
    def __init__(self, irp=None, settings: dict | None = None):
        super().__init__()
        self._irp = irp
        self._settings = settings

    def _steps_for(self, rule_name: str) -> list[dict]:
        return RESPONSE_STEP_CATALOG.get(rule_name, GENERIC_STEPS)

    def run(self, context: dict) -> dict:
        alert_id = context.get("alert_id")
        if alert_id is None:
            raise ValueError("context.alert_id is required")
        rule_name = context.get("rule_name") or ""
        job_id = os.environ.get("SOAR_JOB_ID", "manual")

        settings = self._settings or load_irp_settings()
        irp = self._irp or getattr(connectors, settings["connector"])

        catalog = self._steps_for(rule_name)
        texts = [s["text"] for s in catalog]
        ensured = irp.ensure_response_steps(alert_id, texts)
        steps = ensured.get("steps") or []
        self._logger.info(f"alert {alert_id}: {len(steps)} response steps registered")

        irp.add_comment(
            alert_id,
            f"SOAR: взят в обработку, job {job_id}, шаги зарегистрированы ({len(texts)})",
        )

        # map catalog entries to registered step ids: by text when present,
        # otherwise by order (ensure returns steps in the submitted order)
        by_text = {s.get("text"): s for s in steps if s.get("text")}
        done = 0
        for idx, entry in enumerate(catalog):
            if not entry.get("action"):
                continue
            step = by_text.get(entry["text"]) or (steps[idx] if idx < len(steps) else None)
            if step is None or step.get("done"):
                continue
            self._execute_action(entry["action"], alert_id, irp)
            # marked done only after the action actually ran
            irp.toggle_response_step(alert_id, step["id"], done=True)
            done += 1
            self._logger.info(f"alert {alert_id}: step '{entry['text']}' done")

        return {
            "alert_id": alert_id,
            "rule_name": rule_name,
            "steps_registered": len(texts),
            "steps_completed": done,
            "job_id": job_id,
        }

    def _execute_action(self, action: str, alert_id: int, irp) -> None:
        if action == "collect_context":
            alert = irp.get_alert(alert_id)
            self._logger.info(
                f"alert {alert_id} context: severity={alert.get('severity')} "
                f"rule={alert.get('rule_name')} entity={alert.get('entity')} "
                f"status={alert.get('status')}"
            )
        else:
            raise ValueError(f"unknown response step action '{action}'")
