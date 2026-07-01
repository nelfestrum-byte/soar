import pymysql
import pymysql.cursors

from soar.connectors.base import BaseConnector


class MySQLConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 3306,
        database: str = "",
        user: str = "",
        password: str = "",
        charset: str = "utf8mb4",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.charset = charset
        self._conn: pymysql.Connection | None = None

    def _connect_impl(self):
        self._conn = pymysql.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
            charset=self.charset,
            cursorclass=pymysql.cursors.DictCursor,
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
        with self._conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())

    def execute_raw(self, query: str, params: tuple | None = None) -> dict:
        self._ensure_connected()
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(query, params)
            self._conn.commit()
            return {"rowcount": cur.rowcount, "lastrowid": cur.lastrowid}

    def execute_many(self, query: str, params_list: list[tuple]) -> int:
        self._ensure_connected()
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.executemany(query, params_list)
            self._conn.commit()
            return cur.rowcount

    def tables(self, database: str | None = None) -> list[str]:
        db = database or self.database
        rows = self.execute("SHOW TABLES FROM %s" % db)
        key = f"Tables_in_{db}"
        return [row[key] for row in rows]

    def columns(self, table: str, database: str | None = None) -> list[dict]:
        db = database or self.database
        return self.execute(f"SHOW COLUMNS FROM `{db}`.`{table}`")

    def close(self):
        self.disconnect()
