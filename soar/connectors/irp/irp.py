"""IRP connector — SOC Core Control Alert Inbox / incident lifecycle.

Implements the SOAR side of docs/integration/soc-core-integration-contract.md:
  - flow 1: ingest_alert()            -> POST /api/v2/alerts/ingest
  - flow 3: add_comment(), transition_alert(), ensure_response_steps(),
            toggle_response_step()    -> existing IRP API v2 (writes alert_history)
  - flow 4: send_heartbeat()          -> Redis key orchestrator_heartbeat
            (watched by IRP's UEBA_ORCHESTRATOR_DOWN detector)
  - reconciliation: list_alerts()     -> GET /api/v2/alerts/list

Auth: static M2M token (X-API-Token header) mapped to the soar_service role
on the IRP side. Transition failures that are expected workflow outcomes
(forbidden matrix transition, incomplete response steps) are returned as
{"ok": False, ...}, not raised — workflows branch on them.
"""

import requests

from soar.connectors.base import BaseConnector

_EXPECTED_TRANSITION_ERRORS = (400, 409)


class IRPConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        base_url: str,
        api_token: str,
        verify_ssl: bool = True,
        timeout: int = 15,
        redis_host: str = "",
        redis_port: int = 6379,
        redis_password: str = "",
        redis_db: int = 0,
        heartbeat_key: str = "orchestrator_heartbeat",
        heartbeat_ttl: int = 180,
    ):
        super().__init__(instance_name)
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_password = redis_password
        self.redis_db = redis_db
        self.heartbeat_key = heartbeat_key
        self.heartbeat_ttl = heartbeat_ttl
        self._session: requests.Session | None = None
        self._redis = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        self._session.headers["X-API-Token"] = self.api_token

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
        if self._redis is not None:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None
        self._connected = False
        self._logger.info(f"Disconnected from {self.instance_name}")

    # ── HTTP helpers ─────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v2/alerts{path}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        self._ensure_connected()
        assert self._session is not None
        kwargs.setdefault("timeout", self.timeout)
        return self._session.request(method, self._url(path), **kwargs)

    def _json_or_raise(self, resp: requests.Response) -> dict:
        resp.raise_for_status()
        return resp.json()

    # ── Flow 1: ingest ───────────────────────────────────────────────────

    def ingest_alert(
        self,
        title: str,
        source_ref: str,
        severity: int = 2,
        rule_name: str = "",
        entity: str = "",
        description: str = "",
        observables: list[dict] | None = None,
        tags: list[str] | None = None,
        mitre_tactics: list[str] | None = None,
        event_count: int = 1,
        verdict_score: int | None = None,
        verdict_text: str = "",
        es_doc_id: str = "",
        es_doc_index: str = "",
        alert_type: str = "SOC-Alert",
        source: str = "SOAR",
        triage_run_id: str = "",
        event_time: str = "",
        backfill: bool = False,
    ) -> dict:
        """Create or merge an alert in Alert Inbox.

        Returns {"id": int|None, "action": "created"|"merged"|"skipped"} —
        callers MUST handle all three (skipped = IRP-side ALERT_SKIP_PATTERNS).
        """
        body = {
            "title": title,
            "source_ref": source_ref,
            "severity": severity,
            "rule_name": rule_name or None,
            "entity": entity or None,
            "description": description,
            "observables": observables or [],
            "tags": tags or [],
            "mitre_tactics": mitre_tactics or [],
            "event_count": event_count,
            "verdict_score": verdict_score,
            "verdict_text": verdict_text or None,
            "es_doc_id": es_doc_id or None,
            "es_doc_index": es_doc_index or None,
            "alert_type": alert_type,
            "source": source,
            "triage_run_id": triage_run_id or None,
            "event_time": event_time or None,
            "backfill": backfill,
        }
        return self._json_or_raise(self._request("POST", "/ingest", json=body))

    # ── Reconciliation / reads ───────────────────────────────────────────

    def list_alerts(self, **params) -> dict:
        """GET /list with IRP filter params (status, severity, rule_name, entity,
        hide_noise, min_verdict, limit, offset, ...) — used by the reconciliation
        poller to catch events missed while SOAR was down (contract §5.2)."""
        return self._json_or_raise(self._request("GET", "/list", params=params))

    def get_alert(self, alert_id: int) -> dict:
        return self._json_or_raise(self._request("GET", f"/{alert_id}"))

    # ── Flow 3: writeback ────────────────────────────────────────────────

    def add_comment(self, alert_id: int, body: str) -> dict:
        return self._json_or_raise(
            self._request("POST", f"/{alert_id}/comments", json={"body": body})
        )

    def transition_alert(
        self, alert_id: int, status: str, skip_response_steps: bool = False
    ) -> dict:
        """Move alert through the IRP status matrix. Forbidden transitions and
        incomplete response steps come back as {"ok": False, ...} for workflow
        branching; only unexpected errors raise."""
        resp = self._request(
            "POST",
            f"/{alert_id}/status",
            json={"status": status, "skip_response_steps": skip_response_steps},
        )
        if resp.status_code in _EXPECTED_TRANSITION_ERRORS:
            detail = resp.json().get("detail", "")
            error = detail if isinstance(detail, (dict, list)) else str(detail)
            return {"ok": False, "status_code": resp.status_code, "error": error}
        return self._json_or_raise(resp)

    def ensure_response_steps(self, alert_id: int, texts: list[str]) -> dict:
        """Register workflow steps as the alert's guided-response checklist —
        analysts see automation progress in the IRP UI, and the
        'resolved requires completed steps' gate keeps working."""
        return self._json_or_raise(
            self._request("POST", f"/{alert_id}/response-steps/ensure", json={"texts": texts})
        )

    def get_response_steps(self, alert_id: int) -> dict:
        return self._json_or_raise(self._request("GET", f"/{alert_id}/response-steps"))

    def toggle_response_step(self, alert_id: int, step_id: int, done: bool = True) -> dict:
        return self._json_or_raise(
            self._request("PATCH", f"/{alert_id}/response-steps/{step_id}", json={"done": done})
        )

    # ── Flow 4: heartbeat ────────────────────────────────────────────────

    def send_heartbeat(self) -> bool:
        """SETEX orchestrator_heartbeat in the IRP Redis. Call once per triage
        cycle; TTL must stay above the cycle interval (180s vs 60s cycle) and
        below the ORCHESTRATOR_DOWN detector's stale_after_sec."""
        if not self.redis_host:
            return False
        if self._redis is None:
            import redis

            self._redis = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                password=self.redis_password or None,
                db=self.redis_db,
                socket_timeout=5,
            )
        try:
            self._redis.setex(self.heartbeat_key, self.heartbeat_ttl, "alive")
            return True
        except Exception as e:
            self._logger.warning(f"heartbeat write failed: {e}")
            return False
