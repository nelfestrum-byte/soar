from unittest.mock import MagicMock, patch

import pytest

from soar.connectors.mysql.mysql import MySQLConnector


@pytest.fixture
def conn():
    c = MySQLConnector("test", host="localhost", database="mydb")
    c._connected = True
    return c


def _mock_execute(connector, rows, capture=None):
    """Patch connector.execute and optionally capture the query string."""
    def fake_execute(query, params=None):
        if capture is not None:
            capture.append(query)
        return rows
    connector.execute = fake_execute


def test_tables_uses_backtick_quoting(conn):
    """B2: SHOW TABLES must use backtick-quoted db name, not %-formatting."""
    captured = []
    _mock_execute(conn, [{"Tables_in_mydb": "users"}], capture=captured)

    result = conn.tables()

    assert result == ["users"]
    assert len(captured) == 1
    assert captured[0] == "SHOW TABLES FROM `mydb`"
    # Ensure no %-formatting remnant
    assert "%" not in captured[0]


def test_tables_explicit_db(conn):
    captured = []
    _mock_execute(conn, [{"Tables_in_other": "orders"}], capture=captured)

    result = conn.tables(database="other")

    assert result == ["orders"]
    assert captured[0] == "SHOW TABLES FROM `other`"


def test_tables_invalid_identifier_rejected(conn):
    with pytest.raises(ValueError):
        conn.tables(database="bad;db")
