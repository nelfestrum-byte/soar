from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ConcurrencyPolicy(str, Enum):
    FORBID = "forbid"
    QUEUE = "queue"
    ALLOW = "allow"
