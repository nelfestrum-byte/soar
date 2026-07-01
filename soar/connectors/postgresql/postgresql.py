import psycopg2
import psycopg2.extras

from soar.connectors.base import BaseConnector


class PostgreSQLConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 5432,
        database: str = "",
        user: str = "",
        password: str = "",
        sslmode: str = "prefer",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.sslmode = sslmode
        self._conn: psycopg2.extensions.connection | None = None

    def _connect_impl(self):
        self._conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.database,
            user=self.user,
            password=self.password,
            sslmode=self.sslmode,
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
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def execute_raw(self, query: str, params: tuple | None = None) -> dict:
        self._ensure_connected()
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(query, params)
            self._conn.commit()
            return {"rowcount": cur.rowcount, "statusmessage": cur.statusmessage}

    def execute_many(self, query: str, params_list: list[tuple]) -> int:
        self._ensure_connected()
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.executemany(query, params_list)
            self._conn.commit()
            return cur.rowcount

    def tables(self, schema: str = "public") -> list[str]:
        rows = self.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (schema,),
        )
        return [row["table_name"] for row in rows]

    def columns(self, table: str, schema: str = "public") -> list[dict]:
        return self.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            (schema, table),
        )

    def close(self):
        self.disconnect()
