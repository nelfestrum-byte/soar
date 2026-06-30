from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ConcurrencyPolicy(StrEnum):
    FORBID = "forbid"
    QUEUE = "queue"
    ALLOW = "allow"
