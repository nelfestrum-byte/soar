import pymssql

from soar.connectors.base import BaseConnector


class MSSQLConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 1433,
        database: str = "master",
        user: str = "",
        password: str = "",
        domain: str = "",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.domain = domain
        self._conn: pymssql.Connection | None = None

    def _connect_impl(self):
        self._conn = pymssql.connect(
            server=self.host,
            port=self.port,
            database=self.database,
            user=self.user if not self.domain else f"{self.domain}\\{self.user}",
            password=self.password,
        )

    def disconnect(self):
        if self._conn:
            self._conn.close()
            self._conn = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def execute(self, query: str, params: tuple | None = None) -> list[dict]:
        self._ensure_connected()
        assert self._conn is not None
        cursor = self._conn.cursor(as_dict=True)
        cursor.execute(query, params or ())
        return cursor.fetchall()

    def execute_raw(self, query: str, params: tuple | None = None) -> dict:
        self._ensure_connected()
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.execute(query, params or ())
        self._conn.commit()
        return {"rowcount": cursor.rowcount}

    def execute_many(self, query: str, params_list: list[tuple]) -> int:
        self._ensure_connected()
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.executemany(query, params_list)
        self._conn.commit()
        return cursor.rowcount

    def tables(self, database: str | None = None) -> list[str]:
        db = database or self.database
        rows = self.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_catalog = %s",
            (db,),
        )
        return [row["table_name"] for row in rows]

    def columns(self, table: str, database: str | None = None) -> list[dict]:
        db = database or self.database
        return self.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_catalog = %s AND table_name = %s ORDER BY ordinal_position",
            (db, table),
        )

    def close(self):
        self.disconnect()
