"""Обёртка вокруг BaseConnector-инстанса — единственный способ получить
коннектор что через soar.connectors.connectors.<instance>, что через
from soar.connectors.<type> import <instance>. Оба пути — один механизм с
двумя фасадами (docs/concepts/ENTITY-MODEL.md, решение 4): шим никогда не
отдаёт self._instance напрямую, поэтому прямой импорт не может стать дырой
в обход логирования/dry-run, даже если появится позже."""

import functools
import os
import time
from typing import Any

from soar.connectors.base import BaseConnector
from soar.logger import get_logger
from soar.runtime_state import is_dry_run

_log = get_logger("connector.proxy")


class ConnectorProxy:
    def __init__(self, instance: BaseConnector, type_name: str):
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_type_name", type_name)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._instance, name)
        if name.startswith("_") or not callable(attr):
            return attr
        return self._wrapped(name, attr)

    def __repr__(self) -> str:
        return f"ConnectorProxy({self._type_name}.{self._instance.instance_name})"

    def _wrapped(self, name: str, method):
        hidden = getattr(type(self._instance), "HIDDEN_FIELDS", set())
        mutating = name in getattr(type(self._instance), "MUTATING_METHODS", set())

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            job_id = os.environ.get("SOAR_JOB_ID", "")
            safe_kwargs = {k: ("***" if k in hidden else v) for k, v in kwargs.items()}
            target = f"{self._type_name}.{self._instance.instance_name}.{name}"

            if mutating and is_dry_run():
                _log.bind(audit=True).info(
                    f"SOAR_AUDIT_EVENT connector.call.dry_run target={target} "
                    f"args={args} kwargs={safe_kwargs} job_id={job_id}"
                )
                return None

            start = time.monotonic()
            outcome = "ok"
            try:
                return method(*args, **kwargs)
            except Exception as e:
                outcome = f"error:{type(e).__name__}"
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                _log.bind(audit=True).info(
                    f"SOAR_AUDIT_EVENT connector.call target={target} "
                    f"args={args} kwargs={safe_kwargs} duration_ms={duration_ms} "
                    f"outcome={outcome} job_id={job_id}"
                )
        return wrapper
