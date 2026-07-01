from ldap3 import ALL, Connection, Server, SUBTREE

from soar.connectors.base import BaseConnector


class ActiveDirectoryConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 636,
        base_dn: str = "",
        bind_dn: str = "",
        bind_password: str = "",
        use_ssl: bool = True,
        use_start_tls: bool = False,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.base_dn = base_dn
        self.bind_dn = bind_dn
        self.bind_password = bind_password
        self.use_ssl = use_ssl
        self.use_start_tls = use_start_tls
        self._conn: Connection | None = None

    def _connect_impl(self):
        server = Server(self.host, port=self.port, use_ssl=self.use_ssl, get_info=ALL)
        self._conn = Connection(
            server,
            user=self.bind_dn,
            password=self.bind_password,
            auto_bind=True,
        )
        if self.use_start_tls:
            self._conn.start_tls()

    def disconnect(self):
        if self._conn:
            if self._conn.bound:
                self._conn.unbind()
            self._conn = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def search(self, base_dn: str, filter: str, attributes: list[str] | None = None) -> list[dict]:
        self._ensure_connected()
        assert self._conn is not None
        self._conn.search(
            search_base=base_dn or self.base_dn,
            search_filter=filter,
            attributes=attributes or ["*"],
            search_scope=SUBTREE,
        )
        return [
            {k: v for k, v in entry.entry_attributes_as_dict.items() if v}
            for entry in self._conn.entries
        ]

    def get_user(self, username: str) -> dict | None:
        results = self.search(
            self.base_dn,
            f"(&(objectClass=user)(sAMAccountName={username}))",
        )
        return results[0] if results else None

    def get_user_groups(self, username: str) -> list[str]:
        results = self.search(
            self.base_dn,
            f"(&(objectClass=user)(sAMAccountName={username}))",
            ["memberOf"],
        )
        if not results:
            return []
        member_of = results[0].get("memberOf", [])
        if isinstance(member_of, str):
            member_of = [member_of]
        return member_of

    def get_group_members(self, group_dn: str) -> list[dict]:
        return self.search(
            group_dn,
            "(objectClass=user)",
            ["sAMAccountName", "displayName", "mail", "distinguishedName"],
        )

    def authenticate(self, username: str, password: str) -> bool:
        try:
            server = Server(self.host, port=self.port, use_ssl=self.use_ssl, get_info=ALL)
            test_conn = Connection(server, user=f"{username}@{self.base_dn.split(',')[0].split('=')[1]}", password=password, auto_bind=True)
            test_conn.unbind()
            return True
        except Exception:
            return False

    def modify_attribute(self, dn: str, changes: dict) -> bool:
        self._ensure_connected()
        assert self._conn is not None
        return self._conn.modify(dn, changes)

    def add_user(self, dn: str, attributes: dict) -> bool:
        self._ensure_connected()
        assert self._conn is not None
        return self._conn.add(dn, ["top", "person", "organizationalPerson", "user"], attributes)

    def disable_user(self, dn: str) -> bool:
        return self.modify_attribute(dn, {"userAccountControl": [("MODIFY_REPLACE", [0x0202])]})
