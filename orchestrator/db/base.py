from sqlalchemy.orm import DeclarativeBase

_table_prefix = ""


def configure_table_prefix(prefix: str) -> None:
    """Set the process-wide table prefix. Must be called before any module
    defining ORM models (orchestrator.auth.models, orchestrator.store.models)
    is imported — __tablename__ is fixed at class-definition time."""
    global _table_prefix
    _table_prefix = prefix


def prefixed(name: str) -> str:
    return f"{_table_prefix}{name}"


def fk(table: str, column: str) -> str:
    return f"{prefixed(table)}.{column}"


class Base(DeclarativeBase):
    pass
