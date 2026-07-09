"""SIEM alert triage pipeline (contract §4, plan Task 2, phase 2).

Port of SOC Core's ``wf_siem_alert.py`` + legacy ``process_group`` onto the
orchestrator runtime. Every cycle:

  heartbeat → load_policy → fetch (ES, chunked) → triage per group → ingest
  → advance watermark (per chunk, only after every group ingested)

Delivery model is at-least-once over a durable source (contract §4.3): ES keeps
the alerts, the watermark moves only after a successful ingest of the whole
chunk, replays are absorbed by an idempotent ``source_ref`` built from the
event-time bucket — never from processing time.

Every "do not send" decision is a logged action with a reason and a counter in
``WorkflowResult.data`` — no silent drops (global constraint of the plan).
"""

import hashlib
import os
import re
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from ipaddress import ip_address

from soar.connectors import connectors
from soar.tools.irp_settings import load_irp_settings
from soar.tools.triage_policy import TriagePolicyCache, policy_fetcher
from soar.tools.watermark import WatermarkStore
from soar.workflows.base import ScheduledWorkflow

WATERMARK_KEY = "siem_alerts"

_SEVERITY_MAP = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_SEVERITY_LABEL = {1: "LOW", 2: "MED", 3: "HIGH", 4: "CRIT"}
_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_HASH_FIELDS = ("file.hash.sha256", "file.hash.sha1", "file.hash.md5", "related.hash")
_IP_FIELDS = ("source.ip", "destination.ip", "related.ip")


def _get(doc: dict, dotted: str):
    """Field lookup supporting both flattened ('a.b.c') and nested documents."""
    if dotted in doc:
        return doc[dotted]
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _doc_rule(doc: dict) -> str:
    for field in ("kibana.alert.rule.name", "signal.rule.name", "rule.name", "rule_name"):
        value = _get(doc, field)
        if value:
            return str(value)
    return "unknown-rule"


def _doc_entity(doc: dict) -> str:
    for field in ("host.name", "agent.name", "entity"):
        value = _get(doc, field)
        if value:
            return str(value)
    return "unknown-host"


def _doc_severity(doc: dict) -> int:
    for field in ("kibana.alert.severity", "signal.rule.severity", "severity"):
        value = _get(doc, field)
        if value is None:
            continue
        if isinstance(value, int):
            return max(1, min(4, value))
        mapped = _SEVERITY_MAP.get(str(value).lower())
        if mapped:
            return mapped
    return 2


def _doc_ts(doc: dict) -> str:
    return str(_get(doc, "@timestamp") or _get(doc, "timestamp") or "")


def _matches(patterns: list, rule_name: str, entity: str) -> str | None:
    """Match a group against a policy list. Entries are either strings
    (glob, matched against both rule and entity) or {rule, entity} dicts
    (all present fields must match). Returns the matched pattern for the log."""
    for entry in patterns or []:
        if isinstance(entry, str):
            if fnmatch(rule_name, entry) or fnmatch(entity, entry):
                return entry
        elif isinstance(entry, dict):
            rule_pat = entry.get("rule")
            entity_pat = entry.get("entity")
            rule_ok = rule_pat is None or fnmatch(rule_name, rule_pat)
            entity_ok = entity_pat is None or fnmatch(entity, entity_pat)
            if (rule_pat or entity_pat) and rule_ok and entity_ok:
                return str(entry)
    return None


def make_source_ref(rule_name: str, entity: str, event_time: datetime, window_minutes: int) -> str:
    """Mirror of SOC Core core/alert_payload.py::make_source_ref with the
    event-time bucket (contract §4.3): deterministic for the same rule/entity
    within a wall-clock window grid — replays merge via ON CONFLICT instead of
    duplicating, regardless of how chunks were aligned."""
    bucket_min = (event_time.minute // window_minutes) * window_minutes
    bucket = event_time.replace(minute=bucket_min, second=0, microsecond=0)
    digest = hashlib.sha1(f"{rule_name}|{entity}".encode()).hexdigest()[:8]
    return f"soc-{digest}-{bucket:%Y%m%d-%H%M}"


def calculate_verdict(severity: int, count: int, ti_hits: int | None) -> tuple[int, str]:
    """Port of legacy calculate_verdict: severity dominates, event volume and
    TI reputation raise the score."""
    score = min(100, severity * 15 + min(count, 20) * 2 + (ti_hits or 0) * 20)
    if score >= 70:
        return score, "malicious"
    if score >= 40:
        return score, "suspicious"
    return score, "informational"


def _collect_observables(docs: list[dict]) -> list[dict]:
    """Only public IPs and file hashes (contract §4.2.1) — private IPs glue
    unrelated incidents together on the IRP side."""
    observables: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(data_type: str, value: str):
        key = (data_type, value)
        if value and key not in seen:
            seen.add(key)
            observables.append({"dataType": data_type, "data": value})

    for doc in docs:
        for field in _IP_FIELDS:
            values = _get(doc, field)
            for ip in values if isinstance(values, list) else [values]:
                if not ip:
                    continue
                try:
                    if ip_address(str(ip)).is_global:
                        add("ip", str(ip))
                except ValueError:
                    continue
        for field in _HASH_FIELDS:
            values = _get(doc, field)
            for h in values if isinstance(values, list) else [values]:
                if h:
                    add("hash", str(h))
    return observables


class AlertTriageWorkflow(ScheduledWorkflow):
    interval = 60

    def __init__(self, irp=None, elastic=None, policy_cache=None, watermark=None,
                 settings: dict | None = None, cve_checker=None, ti_enricher=None,
                 now: datetime | None = None):
        super().__init__()
        self._irp = irp
        self._elastic = elastic
        self._policy_cache = policy_cache
        self._watermark = watermark
        self._settings = settings
        # cve_checker(entity, cves) -> True if the host is patched (Wazuh);
        # ti_enricher(observables) -> int TI hits. Both optional: absence is a
        # logged skip, never a silent one.
        self._cve_checker = cve_checker
        self._ti_enricher = ti_enricher
        self._now = now

    # ── fetch ────────────────────────────────────────────────────────────

    def _fetch_chunk(self, elastic, settings: dict, start: datetime, end: datetime) -> list[dict]:
        dsl = {
            "size": int(settings["fetch_size"]),
            "query": {"range": {"@timestamp": {"gte": start.isoformat(), "lt": end.isoformat()}}},
            "sort": [{"@timestamp": "asc"}],
        }
        return elastic.query(settings["alerts_index"], dsl)

    @staticmethod
    def _group(docs: list[dict]) -> dict[tuple[str, str], list[dict]]:
        groups: dict[tuple[str, str], list[dict]] = {}
        for doc in docs:
            groups.setdefault((_doc_rule(doc), _doc_entity(doc)), []).append(doc)
        return groups

    # ── triage ───────────────────────────────────────────────────────────

    def _triage_group(self, rule_name: str, entity: str, docs: list[dict],
                      policies: dict, dropped: dict) -> dict | None:
        """Returns the ingest payload for the group, or None when dropped
        (the reason is already logged and counted)."""
        count = len(docs)
        severity = max(_doc_severity(d) for d in docs)

        matched = _matches(policies["whitelist"], rule_name, entity)
        if matched:
            dropped["whitelist"] += 1
            self._logger.info(
                f"dropped:whitelist rule='{rule_name}' entity='{entity}' pattern={matched}"
            )
            return None

        cves = _CVE_RE.findall(rule_name)
        if cves:
            if self._cve_checker is None:
                self._logger.info(
                    f"cve check skipped (no checker configured) rule='{rule_name}' cves={cves}"
                )
            elif self._cve_checker(entity, cves):
                dropped["cve_patched"] += 1
                self._logger.info(
                    f"dropped:cve_patched rule='{rule_name}' entity='{entity}' cves={cves} "
                    f"(host patched per Wazuh)"
                )
                return None

        escalation = None
        matched = _matches(policies["blacklist"], rule_name, entity)
        if matched:
            escalation = f"blacklist match: {matched}"
        else:
            matched = _matches(policies["critical_assets"], rule_name, entity)
            if matched:
                escalation = f"critical asset: {matched}"
        if escalation:
            severity = 4
            self._logger.info(f"escalated to sev=4 rule='{rule_name}' entity='{entity}' ({escalation})")

        # send gate — legacy behaviour (plan assumption Д-1): sev >= 3 OR count >= threshold
        severity_gate = int(policies["severity_gate"])
        count_threshold = int(policies["count_threshold"])
        if severity < severity_gate and count < count_threshold:
            dropped["below_threshold"] += 1
            self._logger.info(
                f"dropped:below_threshold rule='{rule_name}' entity='{entity}' "
                f"sev {severity} < {severity_gate} and count {count} < {count_threshold}"
            )
            return None

        observables = _collect_observables(docs)
        if self._ti_enricher is None:
            ti_hits = None
            self._logger.info(f"ti enrichment skipped (no enricher configured) rule='{rule_name}'")
        else:
            ti_hits = self._ti_enricher(observables)
        verdict_score, verdict_text = calculate_verdict(severity, count, ti_hits)

        description = (
            f"## VERDICT\n{verdict_text} ({verdict_score}/100)\n\n"
            f"## Context\n- rule: {rule_name}\n- entity: {entity}\n- events: {count}\n"
            + (f"- escalation: {escalation}\n" if escalation else "")
            + (f"- TI hits: {ti_hits}\n" if ti_hits is not None else "")
            + f"\n## SOURCE\n- index: `{_get(docs[0], '_index') or ''}`\n"
            f"- docs: {', '.join(str(d.get('_id', '')) for d in docs[:10])}\n"
        )

        return {
            "title": f"[{_SEVERITY_LABEL[severity]}] {rule_name} @ {entity}",
            "severity": severity,
            "rule_name": rule_name,
            "entity": entity,
            "description": description,
            "observables": observables,
            "event_count": count,
            "verdict_score": verdict_score,
            "verdict_text": verdict_text,
            "es_doc_id": str(docs[0].get("_id", "")),
            "escalation": escalation,
        }

    # ── cycle ────────────────────────────────────────────────────────────

    def run(self, context: dict) -> dict:
        settings = self._settings or load_irp_settings()
        if not settings.get("enabled"):
            self._logger.info("IRP integration disabled in config, cycle skipped")
            return {"skipped": "irp integration disabled"}

        irp = self._irp or getattr(connectors, settings["connector"])
        elastic = self._elastic or getattr(connectors, settings["elastic_connector"])
        wm_store = self._watermark or WatermarkStore(settings["watermark_path"])
        policy_cache = self._policy_cache or TriagePolicyCache(
            policy_fetcher(
                irp.base_url, irp.api_token, settings["policy_endpoint"],
                verify_ssl=irp.verify_ssl, timeout=irp.timeout,
            ),
            settings["policy_cache_path"],
            ttl=int(settings["policy_ttl"]),
        )

        # heartbeat first: a cycle that dies mid-way must not look alive
        if not irp.send_heartbeat():
            self._logger.warning("heartbeat write failed (continuing the cycle)")

        # no cache + API down raises TriagePolicyError and aborts the cycle:
        # triaging with empty policies is worse than a missed cycle
        policies = policy_cache.get()

        now = self._now or datetime.now(UTC)
        window = timedelta(minutes=int(settings["time_window_minutes"]))
        overlap = timedelta(minutes=int(settings["overlap_minutes"]))

        watermark = wm_store.get(WATERMARK_KEY)
        if watermark is None:
            start = now - window  # first run: never from the epoch
            self._logger.info(f"no watermark, starting from {start.isoformat()}")
        else:
            start = datetime.fromisoformat(watermark) - overlap

        chunks: list[tuple[datetime, datetime]] = []
        cursor = start
        while cursor < now:
            chunk_end = min(cursor + window, now)
            chunks.append((cursor, chunk_end))
            cursor = chunk_end
        backfill = len(chunks) > 1
        if backfill:
            self._logger.info(f"backfill mode: {len(chunks)} chunks of {window} to catch up")

        shadow = bool(settings.get("shadow", True))
        tags = ["sys:soar"] + (["soar:shadow"] if shadow else [])
        triage_run_id = os.environ.get("SOAR_JOB_ID", "")
        window_minutes = int(settings["time_window_minutes"])

        result = {
            "fetched": 0, "ingested_created": 0, "ingested_merged": 0, "skipped_irp": 0,
            "dropped": {"whitelist": 0, "cve_patched": 0, "below_threshold": 0},
            "backfill_chunks": len(chunks) if backfill else 0,
            "watermark": watermark,
        }

        for chunk_start, chunk_end in chunks:
            docs = self._fetch_chunk(elastic, settings, chunk_start, chunk_end)
            result["fetched"] += len(docs)

            for (rule_name, entity), group_docs in self._group(docs).items():
                payload = self._triage_group(rule_name, entity, group_docs, policies, result["dropped"])
                if payload is None:
                    continue
                escalation = payload.pop("escalation")
                event_ts = min(_doc_ts(d) for d in group_docs) or chunk_start.isoformat()
                source_ref = make_source_ref(
                    rule_name, entity, datetime.fromisoformat(event_ts), window_minutes
                )
                ingest_tags = tags + (["priority:critical"] if escalation else [])
                # any exception here aborts the cycle before the watermark
                # moves — replay of the whole chunk is idempotent by source_ref
                response = irp.ingest_alert(
                    source_ref=source_ref,
                    tags=ingest_tags,
                    es_doc_index=settings["alerts_index"],
                    triage_run_id=triage_run_id,
                    event_time=chunk_end.isoformat(),
                    backfill=backfill,
                    **payload,
                )
                action = response.get("action")
                if action == "created":
                    result["ingested_created"] += 1
                elif action == "merged":
                    result["ingested_merged"] += 1
                else:
                    # skipped = IRP-side ALERT_SKIP_PATTERNS — their source of truth
                    result["skipped_irp"] += 1
                    self._logger.info(
                        f"skipped by IRP rule='{rule_name}' entity='{entity}' (ALERT_SKIP_PATTERNS)"
                    )

            # the whole chunk ingested — only now the watermark may move
            wm_store.set(WATERMARK_KEY, chunk_end.isoformat())
            result["watermark"] = chunk_end.isoformat()

        self._logger.info(
            f"cycle done: fetched={result['fetched']} created={result['ingested_created']} "
            f"merged={result['ingested_merged']} skipped={result['skipped_irp']} "
            f"dropped={result['dropped']} watermark={result['watermark']}"
        )
        return result
