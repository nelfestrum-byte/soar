# SOAR Enterprise Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all existing connectors/actions/workflows with enterprise-grade SOAR connectors covering standard security tools and infrastructure.

**Architecture:** Each connector extends `BaseConnector`, implements `_connect_impl()` for lazy init, and exposes API methods directly. No wrappers around wrappers — methods map 1:1 to the underlying tool's API.

**Tech Stack:** Python 3.11+, paramiko (SSH), ldap3 (AD/FreeIPA), elasticsearch-py, requests (REST APIs), psycopg2/pymysql/pymssql (databases), aiogram (Telegram), smtplib (SMTP), vt-py (VirusTotal)

## Global Constraints

- Python 3.11+
- Each connector in its own directory: `soar/connectors/<name>/`
- Each directory: `__init__.py` + `<name>.py` (main connector class)
- Class naming: `<Name>Connector` (e.g., `SSHConnector`)
- All connectors extend `BaseConnector` from `soar/connectors/base.py`
- Lazy connection via `_connect_impl()` + `_ensure_connected()`
- No comments in code unless explaining non-obvious behavior
- Methods return raw API responses (dicts/lists) — no normalization

---

## Task 1: Delete All Old Code

**Files:**
- Delete: `soar/connectors/elastic/`, `soar/connectors/telegram/`, `soar/connectors/smtp/`, `soar/connectors/virus_total/`, `soar/connectors/file/`
- Delete: `soar/actions/` (all files except `__init__.py`)
- Delete: `soar/workflows/alert_check.py`, `soar/workflows/webhook_to_file.py`

- [ ] **Step 1: Delete old connector directories**

```bash
rm -rf soar/connectors/elastic soar/connectors/telegram soar/connectors/smtp soar/connectors/virus_total soar/connectors/file
```

- [ ] **Step 2: Delete old actions (keep __init__.py)**

```bash
rm soar/actions/send_tg_soc_team.py
```

- [ ] **Step 3: Delete old workflows**

```bash
rm soar/workflows/alert_check.py soar/workflows/webhook_to_file.py
```

- [ ] **Step 4: Verify cleanup**

```bash
ls soar/connectors/
ls soar/actions/
ls soar/workflows/
```

Expected: Only `base.py`, `__init__.py` in connectors; `__init__.py` in actions; `base.py`, `__init__.py` in workflows.

---

## Task 2: Update Dependencies

**Files:**
- Modify: `soar/requirements.txt`

- [ ] **Step 1: Update requirements.txt**

```txt
loguru>=0.7.0
pyyaml>=6.0
elasticsearch>=8.0.0
vt-py>=0.17.0
paramiko>=3.4.0
ldap3>=2.9.1
requests>=2.31.0
httpx>=0.27.0
psycopg2-binary>=2.9.9
pymysql>=1.1.0
pymssql>=2.2.11
aiogram>=3.7.0
aiosmtplib>=3.0.1
```

- [ ] **Step 2: Verify no import errors**

```bash
python -c "import paramiko, ldap3, requests, httpx, pymysql, pymssql, aiogram, aiosmtplib"
```

---

## Task 3: SSH Connector

**Files:**
- Create: `soar/connectors/ssh/__init__.py`
- Create: `soar/connectors/ssh/ssh.py`

**Interface:**
- `_connect_impl()`: Establish paramiko SSH connection
- `exec_command(command: str, timeout: int = 30) -> dict`: Execute command, return stdout/stderr/exit_code
- `put_file(local_path: str, remote_path: str) -> bool`: Upload file
- `get_file(remote_path: str, local_path: str) -> bool`: Download file
- `list_dir(path: str = "/") -> list[str]`: List directory contents

- [ ] **Step 1: Create ssh/__init__.py**

```python
from soar.connectors.ssh.ssh import SSHConnector

__all__ = ["SSHConnector"]
```

- [ ] **Step 2: Create ssh/ssh.py**

```python
import paramiko

from soar.connectors.base import BaseConnector


class SSHConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 22,
        username: str = "",
        password: str = "",
        key_filename: str = "",
        timeout: int = 10,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.timeout = timeout
        self._client: paramiko.SSHClient | None = None

    def _connect_impl(self):
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }
        if self.key_filename:
            connect_kwargs["key_filename"] = self.key_filename
        elif self.password:
            connect_kwargs["password"] = self.password
        self._client.connect(**connect_kwargs)

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def exec_command(self, command: str, timeout: int = 30) -> dict:
        self._ensure_connected()
        assert self._client is not None
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return {
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "exit_code": exit_code,
        }

    def put_file(self, local_path: str, remote_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
            return True
        finally:
            sftp.close()

    def get_file(self, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        sftp = self._client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
            return True
        finally:
            sftp.close()

    def list_dir(self, path: str = "/") -> list[str]:
        self._ensure_connected()
        assert self._client is not None
        sftp = self._client.open_sftp()
        try:
            return sftp.listdir(path)
        finally:
            sftp.close()
```

---

## Task 4: Active Directory Connector

**Files:**
- Create: `soar/connectors/active_directory/__init__.py`
- Create: `soar/connectors/active_directory/active_directory.py`

**Interface:**
- `_connect_impl()`: Bind to LDAP server
- `search(base_dn: str, filter: str, attributes: list[str]) -> list[dict]`: LDAP search
- `get_user(username: str) -> dict | None`: Get user by sAMAccountName
- `get_user_groups(username: str) -> list[str]`: Get user's group DN list
- `get_group_members(group_dn: str) -> list[dict]`: Get group members
- `authenticate(username: str, password: str) -> bool`: Bind test
- `modify_attribute(dn: str, changes: dict) -> bool`: Modify LDAP attribute
- `add_user(dn: str, attributes: dict) -> bool`: Add user entry
- `disable_user(dn: str) -> bool`: Disable user (set userAccountControl)

- [ ] **Step 1: Create active_directory/__init__.py**

```python
from soar.connectors.active_directory.active_directory import ActiveDirectoryConnector

__all__ = ["ActiveDirectoryConnector"]
```

- [ ] **Step 2: Create active_directory/active_directory.py**

```python
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
```

---

## Task 5: FreeIPA Connector

**Files:**
- Create: `soar/connectors/freeipa/__init__.py`
- Create: `soar/connectors/freeipa/freeipa.py`

**Interface:**
- `_connect_impl()`: Connect to FreeIPA API via requests with session auth
- `user_find criteria: str = "" -> list[dict]`: Find users
- `user_show(uid: str) -> dict`: Get user details
- `user_add(uid: str, given_name: str, sn: str, **kwargs) -> dict`: Add user
- `user_disable(uid: str) -> dict`: Disable user
- `user_enable(uid: str) -> dict`: Enable user
- `group_find(criteria: str = "") -> list[dict]`: Find groups
- `group_show(cn: str) -> dict`: Get group details
- `host_find(criteria: str = "") -> list[dict]`: Find hosts
- `host_show(fqdn: str) -> dict`: Get host details
- `hbac_rule_find() -> list[dict]`: Find HBAC rules
- `cert_find() -> list[dict]`: Find certificates

- [ ] **Step 1: Create freeipa/__init__.py**

```python
from soar.connectors.freeipa.freeipa import FreeIPAConnector

__all__ = ["FreeIPAConnector"]
```

- [ ] **Step 2: Create freeipa/freeipa.py**

```python
import json

import requests

from soar.connectors.base import BaseConnector


class FreeIPAConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 443,
        username: str = "",
        password: str = "",
        verify_ssl: bool = True,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None
        self._base_url: str = ""

    def _connect_impl(self):
        self._base_url = f"https://{self.host}:{self.port}"
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        login_url = f"{self._base_url}/ipa/session/login_password"
        resp = self._session.post(
            login_url,
            data={"user": self.username, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _api_call(self, method: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._session is not None
        url = f"{self._base_url}/ipa/json"
        payload = {
            "method": method,
            "params": params or [],
            "options": {},
        }
        resp = self._session.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise Exception(f"FreeIPA error: {data['error']}")
        return data.get("result", {})

    def user_find(self, criteria: str = "") -> list[dict]:
        params = [["user_find"], {"criteria": criteria}]
        result = self._api_call("user_find", params)
        return result.get("result", [])

    def user_show(self, uid: str) -> dict:
        params = [["user_show"], {"uid": uid}]
        return self._api_call("user_show", params)

    def user_add(self, uid: str, given_name: str, sn: str, **kwargs) -> dict:
        params = [["user_add"], {"uid": uid, "givenname": given_name, "sn": sn, **kwargs}]
        return self._api_call("user_add", params)

    def user_disable(self, uid: str) -> dict:
        params = [["user_disable"], {"uid": uid}]
        return self._api_call("user_disable", params)

    def user_enable(self, uid: str) -> dict:
        params = [["user_enable"], {"uid": uid}]
        return self._api_call("user_enable", params)

    def group_find(self, criteria: str = "") -> list[dict]:
        params = [["group_find"], {"criteria": criteria}]
        result = self._api_call("group_find", params)
        return result.get("result", [])

    def group_show(self, cn: str) -> dict:
        params = [["group_show"], {"cn": cn}]
        return self._api_call("group_show", params)

    def host_find(self, criteria: str = "") -> list[dict]:
        params = [["host_find"], {"criteria": criteria}]
        result = self._api_call("host_find", params)
        return result.get("result", [])

    def host_show(self, fqdn: str) -> dict:
        params = [["host_show"], {"fqdn": fqdn}]
        return self._api_call("host_show", params)

    def hbac_rule_find(self) -> list[dict]:
        params = [["hbac_rule_find"], {}]
        result = self._api_call("hbac_rule_find", params)
        return result.get("result", [])

    def cert_find(self) -> list[dict]:
        params = [["cert_find"], {}]
        result = self._api_call("cert_find", params)
        return result.get("result", [])
```

---

## Task 6: Elastic Connector (Rewrite)

**Files:**
- Create: `soar/connectors/elastic/__init__.py`
- Create: `soar/connectors/elastic/elastic.py`

**Interface:**
- `_connect_impl()`: Init Elasticsearch client
- `query(index: str, dsl: dict) -> list[dict]`: Search
- `index(index: str, document: dict) -> dict`: Index document
- `delete(index: str, doc_id: str) -> dict`: Delete document
- `bulk(index: str, documents: list[dict]) -> dict`: Bulk index
- `get(index: str, doc_id: str) -> dict`: Get document by ID
- `update(index: str, doc_id: str, doc: dict) -> dict`: Update document
- `indices_exists(index: str) -> bool`: Check if index exists
- `indices_create(index: str, mappings: dict) -> dict`: Create index
- `indices_delete(index: str) -> dict`: Delete index
- `cat_indices() -> list[dict]`: List all indices
- `ilm_get_policy(policy: str) -> dict`: Get ILM policy

- [ ] **Step 1: Create elastic/__init__.py**

```python
from soar.connectors.elastic.elastic import ElasticConnector

__all__ = ["ElasticConnector"]
```

- [ ] **Step 2: Create elastic/elastic.py**

```python
from elasticsearch import Elasticsearch

from soar.connectors.base import BaseConnector


class ElasticConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 9200,
        api_key: str = "",
        username: str = "",
        password: str = "",
        verify_certs: bool = True,
        ca_cert: str = "",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.api_key = api_key
        self.username = username
        self.password = password
        self.verify_certs = verify_certs
        self.ca_cert = ca_cert
        self._client: Elasticsearch | None = None

    def _connect_impl(self):
        kwargs: dict = {
            "hosts": [f"https://{self.host}:{self.port}"],
            "verify_certs": self.verify_certs,
        }
        if self.ca_cert:
            kwargs["ca_certs"] = self.ca_cert
        if self.api_key:
            kwargs["api_key"] = self.api_key
        elif self.username and self.password:
            kwargs["basic_auth"] = (self.username, self.password)
        self._client = Elasticsearch(**kwargs)

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def query(self, index: str, dsl: dict) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.search(index=index, body=dsl)
        return [hit["_source"] | {"_id": hit["_id"]} for hit in resp["hits"]["hits"]]

    def index(self, index: str, document: dict) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.index(index=index, body=document)

    def delete(self, index: str, doc_id: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.delete(index=index, id=doc_id)

    def bulk(self, index: str, documents: list[dict]) -> dict:
        self._ensure_connected()
        assert self._client is not None
        actions = []
        for doc in documents:
            actions.append({"index": {"_index": index}})
            actions.append(doc)
        return self._client.bulk(operations=actions)

    def get(self, index: str, doc_id: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.get(index=index, id=doc_id)
        return resp["_source"] | {"_id": resp["_id"]}

    def update(self, index: str, doc_id: str, doc: dict) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.update(index=index, id=doc_id, body={"doc": doc})

    def indices_exists(self, index: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        return self._client.indices.exists(index=index).meta.status == 200

    def indices_create(self, index: str, mappings: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._client is not None
        kwargs: dict = {}
        if mappings:
            kwargs["mappings"] = mappings
        return self._client.indices.create(index=index, **kwargs)

    def indices_delete(self, index: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.indices.delete(index=index)

    def cat_indices(self) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        resp = self._client.cat.indices(format="json", h="index,health,docs.count,store.size")
        return resp

    def ilm_get_policy(self, policy: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.ilm.get_lifecycle(policy=policy)
```

---

## Task 7: Security Onion Connector

**Files:**
- Create: `soar/connectors/security_onion/__init__.py`
- Create: `soar/connectors/security_onion/security_onion.py`

**Interface:**
- `_connect_impl()`: Init session with auth
- `query(index: str, query: str, range_start: str, range_end: str, size: int = 100) -> list[dict]`: Elasticsearch query via Security Onion API
- `get_alerts(index: str = "so-*-alert*") -> list[dict]`: Get alerts
- `get_events(index: str = "so-*-events*") -> list[dict]`: Get events
- `get_agents() -> list[dict]`: List agents (endpoint security)
- `get_detections() -> list[dict]`: Get detection rules
- `get_hunts(query: str) -> list[dict]`: Hunt queries
- `get_pcap(event_id: str) -> bytes`: Get PCAP data

- [ ] **Step 1: Create security_onion/__init__.py**

```python
from soar.connectors.security_onion.security_onion import SecurityOnionConnector

__all__ = ["SecurityOnionConnector"]
```

- [ ] **Step 2: Create security_onion/security_onion.py**

```python
from datetime import UTC, datetime, timedelta

import requests

from soar.connectors.base import BaseConnector


class SecurityOnionConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 443,
        username: str = "",
        password: str = "",
        verify_ssl: bool = True,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None
        self._base_url: str = ""

    def _connect_impl(self):
        self._base_url = f"https://{self.host}:{self.port}"
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        login_url = f"{self._base_url}/api/auth"
        resp = self._session.post(login_url, json={"username": self.username, "password": self.password})
        resp.raise_for_status()
        token = resp.json().get("token")
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _search(self, index: str, query: dict, size: int = 100) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        url = f"{self._base_url}/api/elastic/{index}/_search"
        payload = {"query": query, "size": size}
        resp = self._session.post(url, json=payload)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return [hit["_source"] | {"_id": hit["_id"]} for hit in hits]

    def query(self, index: str, query: str, range_start: str | None = None, range_end: str | None = None, size: int = 100) -> list[dict]:
        if not range_end:
            range_end = datetime.now(UTC).isoformat()
        if not range_start:
            range_start = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        dsl = {
            "bool": {
                "must": [{"query_string": {"query": query}}],
                "filter": [{"range": {"@timestamp": {"gte": range_start, "lte": range_end}}}],
            }
        }
        return self._search(index, dsl, size)

    def get_alerts(self, index: str = "so-*-alert*", size: int = 100) -> list[dict]:
        return self._search(index, {"match_all": {}}, size)

    def get_events(self, index: str = "so-*-events*", size: int = 100) -> list[dict]:
        return self._search(index, {"match_all": {}}, size)

    def get_agents(self) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self._base_url}/api/agents")
        resp.raise_for_status()
        return resp.json()

    def get_detections(self) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self._base_url}/api/detections")
        resp.raise_for_status()
        return resp.json()

    def get_hunts(self, query: str) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(f"{self._base_url}/api/hunts", json={"query": query})
        resp.raise_for_status()
        return resp.json()

    def get_pcap(self, event_id: str) -> bytes:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self._base_url}/api/pcap/{event_id}")
        resp.raise_for_status()
        return resp.content
```

---

## Task 8: Wazuh Connector

**Files:**
- Create: `soar/connectors/wazuh/__init__.py`
- Create: `soar/connectors/wazuh/wazuh.py`

**Interface:**
- `_connect_impl()`: Init Wazuh API session
- `get_agents(status: str = "active") -> list[dict]`: Get agents
- `get_agent(agent_id: str) -> dict`: Get agent details
- `get_alerts(rule_id: int | None = None, limit: int = 100) -> list[dict]`: Get alerts
- `get_sca(agent_id: str) -> list[dict]`: Get SCA results
- `get_vulnerabilities(agent_id: str) -> list[dict]`: Get vulnerabilities
- `get_syscheck(agent_id: str) -> list[dict]`: Get file integrity monitoring
- `get_rootcheck(agent_id: str) -> list[dict]`: Get rootcheck results
- `get_rules() -> list[dict]`: Get detection rules
- `get_decoders() -> list[dict]`: Get decoders
- `restart_agent(agent_id: str) -> dict`: Restart agent

- [ ] **Step 1: Create wazuh/__init__.py**

```python
from soar.connectors.wazuh.wazuh import WazuhConnector

__all__ = ["WazuhConnector"]
```

- [ ] **Step 2: Create wazuh/wazuh.py**

```python
import requests
import urllib3

from soar.connectors.base import BaseConnector

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class WazuhConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 55000,
        username: str = "admin",
        password: str = "admin",
        verify_ssl: bool = False,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._token: str = ""
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.verify = self.verify_ssl
        resp = self._session.post(
            f"https://{self.host}:{self.port}/security/user/authenticate",
            auth=(self.username, self.password),
        )
        resp.raise_for_status()
        self._token = resp.json()["data"]["token"]
        self._session.headers["Authorization"] = f"Bearer {self._token}"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"https://{self.host}:{self.port}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, params: dict | None = None) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.put(f"https://{self.host}:{self.port}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_agents(self, status: str = "active") -> list[dict]:
        data = self._get("/agents", params={"status": status, "limit": 500})
        return data.get("data", {}).get("affected_items", [])

    def get_agent(self, agent_id: str) -> dict:
        data = self._get(f"/agents/{agent_id}")
        items = data.get("data", {}).get("affected_items", [])
        return items[0] if items else {}

    def get_alerts(self, rule_id: int | None = None, limit: int = 100) -> list[dict]:
        params: dict = {"limit": limit}
        if rule_id:
            params["rule_id"] = rule_id
        data = self._get("/alerts", params=params)
        return data.get("data", {}).get("affected_items", [])

    def get_sca(self, agent_id: str) -> list[dict]:
        data = self._get(f"/sca/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_vulnerabilities(self, agent_id: str) -> list[dict]:
        data = self._get(f"/vulnerability/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_syscheck(self, agent_id: str) -> list[dict]:
        data = self._get(f"/syscheck/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_rootcheck(self, agent_id: str) -> list[dict]:
        data = self._get(f"/rootcheck/{agent_id}")
        return data.get("data", {}).get("affected_items", [])

    def get_rules(self) -> list[dict]:
        data = self._get("/rules")
        return data.get("data", {}).get("affected_items", [])

    def get_decoders(self) -> list[dict]:
        data = self._get("/decoders")
        return data.get("data", {}).get("affected_items", [])

    def restart_agent(self, agent_id: str) -> dict:
        return self._put(f"/agents/{agent_id}/restart")
```

---

## Task 9: PostgreSQL Connector

**Files:**
- Create: `soar/connectors/postgresql/__init__.py`
- Create: `soar/connectors/postgresql/postgresql.py`

**Interface:**
- `_connect_impl()`: Create psycopg2 connection
- `execute(query: str, params: tuple | None = None) -> list[dict]`: Execute SELECT, return rows
- `execute_raw(query: str, params: tuple | None = None) -> dict`: Execute INSERT/UPDATE/DELETE, return rowcount
- `execute_many(query: str, params_list: list[tuple]) -> int`: Execute many, return rowcount
- `tables(schema: str = "public") -> list[str]`: List tables
- `columns(table: str, schema: str = "public") -> list[dict]`: Get table columns
- `close()`: Close connection

- [ ] **Step 1: Create postgresql/__init__.py**

```python
from soar.connectors.postgresql.postgresql import PostgreSQLConnector

__all__ = ["PostgreSQLConnector"]
```

- [ ] **Step 2: Create postgresql/postgresql.py**

```python
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
```

---

## Task 10: MySQL Connector

**Files:**
- Create: `soar/connectors/mysql/__init__.py`
- Create: `soar/connectors/mysql/mysql.py`

**Interface:**
- `_connect_impl()`: Create pymysql connection
- `execute(query: str, params: tuple | None = None) -> list[dict]`: Execute SELECT
- `execute_raw(query: str, params: tuple | None = None) -> dict`: Execute DML
- `execute_many(query: str, params_list: list[tuple]) -> int`: Execute many
- `tables(database: str | None = None) -> list[str]`: List tables
- `columns(table: str, database: str | None = None) -> list[dict]`: Get columns
- `close()`: Close connection

- [ ] **Step 1: Create mysql/__init__.py**

```python
from soar.connectors.mysql.mysql import MySQLConnector

__all__ = ["MySQLConnector"]
```

- [ ] **Step 2: Create mysql/mysql.py**

```python
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
```

---

## Task 11: MSSQL Connector

**Files:**
- Create: `soar/connectors/mssql/__init__.py`
- Create: `soar/connectors/mssql/mssql.py`

**Interface:**
- `_connect_impl()`: Create pymssql connection
- `execute(query: str, params: tuple | None = None) -> list[dict]`: Execute SELECT
- `execute_raw(query: str, params: tuple | None = None) -> dict`: Execute DML
- `execute_many(query: str, params_list: list[tuple]) -> int`: Execute many
- `tables(database: str | None = None) -> list[str]`: List tables
- `columns(table: str, database: str | None = None) -> list[dict]`: Get columns
- `close()`: Close connection

- [ ] **Step 1: Create mssql/__init__.py**

```python
from soar.connectors.mssql.mssql import MSSQLConnector

__all__ = ["MSSQLConnector"]
```

- [ ] **Step 2: Create mssql/mssql.py**

```python
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
```

---

## Task 12: Telegram Connector (Rewrite)

**Files:**
- Create: `soar/connectors/telegram/__init__.py`
- Create: `soar/connectors/telegram/telegram.py`

**Interface:**
- `_connect_impl()`: Init aiogram Bot
- `send_message(chat_id: str, text: str, parse_mode: str = "") -> dict`: Send message
- `send_photo(chat_id: str, photo: str, caption: str = "") -> dict`: Send photo
- `send_document(chat_id: str, document: str, caption: str = "") -> dict`: Send document
- `send_animation(chat_id: str, animation: str, caption: str = "") -> dict`: Send GIF
- `get_updates(offset: int = 0, limit: int = 100) -> list[dict]`: Get pending updates
- `get_chat(chat_id: str) -> dict`: Get chat info
- `get_me() -> dict`: Get bot info

- [ ] **Step 1: Create telegram/__init__.py**

```python
from soar.connectors.telegram.telegram import TelegramConnector

__all__ = ["TelegramConnector"]
```

- [ ] **Step 2: Create telegram/telegram.py**

```python
import asyncio

from aiogram import Bot
from aiogram.enums import ParseMode

from soar.connectors.base import BaseConnector


class TelegramConnector(BaseConnector):
    def __init__(self, instance_name: str, token: str, parse_mode: str = ""):
        super().__init__(instance_name)
        self.token = token
        self._parse_mode = parse_mode
        self._bot: Bot | None = None

    def _connect_impl(self):
        self._bot = Bot(token=self.token)

    def disconnect(self):
        if self._bot:
            self._bot = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return loop.run_in_executor(pool, lambda: asyncio.run(coro))
        except RuntimeError:
            return asyncio.run(coro)

    def send_message(self, chat_id: str, text: str, parse_mode: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            pm = parse_mode or self._parse_mode
            kwargs = {"chat_id": chat_id, "text": text}
            if pm:
                kwargs["parse_mode"] = ParseMode(pm.upper()) if pm.upper() in ["HTML", "MARKDOWN"] else pm
            msg = await self._bot.send_message(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def send_photo(self, chat_id: str, photo: str, caption: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            kwargs: dict = {"chat_id": chat_id, "photo": photo}
            if caption:
                kwargs["caption"] = caption
            msg = await self._bot.send_photo(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def send_document(self, chat_id: str, document: str, caption: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            kwargs: dict = {"chat_id": chat_id, "document": document}
            if caption:
                kwargs["caption"] = caption
            msg = await self._bot.send_document(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def send_animation(self, chat_id: str, animation: str, caption: str = "") -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _send():
            kwargs: dict = {"chat_id": chat_id, "animation": animation}
            if caption:
                kwargs["caption"] = caption
            msg = await self._bot.send_animation(**kwargs)
            return {"message_id": msg.message_id, "chat": {"id": msg.chat.id}}

        result = self._run(_send())
        return result if isinstance(result, dict) else {}

    def get_updates(self, offset: int = 0, limit: int = 100) -> list[dict]:
        self._ensure_connected()
        assert self._bot is not None

        async def _get():
            updates = await self._bot.get_updates(offset=offset, limit=limit)
            return [
                {
                    "update_id": u.update_id,
                    "message": {
                        "message_id": u.message.message_id,
                        "chat": {"id": u.message.chat.id},
                        "text": u.message.text,
                        "from": {"id": u.message.from_user.id, "username": u.message.from_user.username} if u.message.from_user else None,
                    } if u.message else None,
                }
                for u in updates
            ]

        result = self._run(_get())
        return result if isinstance(result, list) else []

    def get_chat(self, chat_id: str) -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _get():
            chat = await self._bot.get_chat(chat_id)
            return {"id": chat.id, "type": chat.type, "title": chat.title, "username": chat.username}

        result = self._run(_get())
        return result if isinstance(result, dict) else {}

    def get_me(self) -> dict:
        self._ensure_connected()
        assert self._bot is not None

        async def _get():
            me = await self._bot.get_me()
            return {"id": me.id, "username": me.username, "first_name": me.first_name, "is_bot": me.is_bot}

        result = self._run(_get())
        return result if isinstance(result, dict) else {}
```

---

## Task 13: SMTP Connector (Rewrite)

**Files:**
- Create: `soar/connectors/smtp/__init__.py`
- Create: `soar/connectors/smtp/smtp.py`

**Interface:**
- `_connect_impl()`: Init SMTP session
- `send_email(to: str | list[str], subject: str, body: str, html: bool = False, attachments: list[dict] = []) -> dict`: Send email
- `send_text(to: str | list[str], subject: str, body: str) -> dict`: Send plain text
- `send_html(to: str | list[str], subject: str, html: str) -> dict`: Send HTML
- `disconnect()`: Close SMTP

- [ ] **Step 1: Create smtp/__init__.py**

```python
from soar.connectors.smtp.smtp import SMTPConnector

__all__ = ["SMTPConnector"]
```

- [ ] **Step 2: Create smtp/smtp.py**

```python
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from soar.connectors.base import BaseConnector


class SMTPConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str = "localhost",
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        from_address: str = "",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.from_address = from_address
        self._server: smtplib.SMTP | smtplib.SMTP_SSL | None = None

    def _connect_impl(self):
        if self.use_ssl:
            self._server = smtplib.SMTP_SSL(self.host, self.port)
        else:
            self._server = smtplib.SMTP(self.host, self.port)
            if self.use_tls:
                self._server.starttls()
        if self.username and self.password:
            self._server.login(self.username, self.password)

    def disconnect(self):
        if self._server:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _build_message(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        html: bool = False,
        attachments: list[dict] | None = None,
    ) -> MIMEMultipart:
        recipients = [to] if isinstance(to, str) else to
        msg = MIMEMultipart()
        msg["From"] = self.from_address
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))
        for att in attachments or []:
            with open(att["path"], "rb") as f:
                part = MIMEApplication(f.read(), Name=att.get("name", att["path"].split("/")[-1]))
            part["Content-Disposition"] = f'attachment; filename="{att.get("name", att["path"].split("/")[-1])}"'
            msg.attach(part)
        return msg

    def _send(self, msg: MIMEMultipart) -> dict:
        self._ensure_connected()
        assert self._server is not None
        recipients = msg["To"].split(", ")
        self._server.sendmail(self.from_address, recipients, msg.as_string())
        return {"status": "sent", "recipients": recipients}

    def send_email(self, to: str | list[str], subject: str, body: str, html: bool = False, attachments: list[dict] | None = None) -> dict:
        msg = self._build_message(to, subject, body, html, attachments)
        return self._send(msg)

    def send_text(self, to: str | list[str], subject: str, body: str) -> dict:
        return self.send_email(to, subject, body, html=False)

    def send_html(self, to: str | list[str], subject: str, html: str) -> dict:
        return self.send_email(to, subject, html, html=True)
```

---

## Task 14: VirusTotal Connector (Rewrite)

**Files:**
- Create: `soar/connectors/virus_total/__init__.py`
- Create: `soar/connectors/virus_total/virus_total.py`

**Interface:**
- `_connect_impl()`: Init vt-py client
- `get_ip_report(ip: str) -> dict`: IP address report
- `get_domain_report(domain: str) -> dict`: Domain report
- `get_file_report(hash: str) -> dict`: File hash report
- `get_url_report(url: str) -> dict`: URL report
- `upload_file(file_path: str) -> dict`: Upload file for analysis
- `get_file_behaviour(hash: str) -> dict`: Get behaviour report
- `get_file_sandbox(hash: str) -> dict`: Get sandbox results

- [ ] **Step 1: Create virus_total/__init__.py**

```python
from soar.connectors.virus_total.virus_total import VirusTotalConnector

__all__ = ["VirusTotalConnector"]
```

- [ ] **Step 2: Create virus_total/virus_total.py**

```python
import vt

from soar.connectors.base import BaseConnector


class VirusTotalConnector(BaseConnector):
    def __init__(self, instance_name: str, api_key: str):
        super().__init__(instance_name)
        self.api_key = api_key
        self._client: vt.Client | None = None

    def _connect_impl(self):
        self._client = vt.Client(self.api_key)

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def get_ip_report(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/ip_addresses/{ip}")
        return dict(obj)

    def get_domain_report(self, domain: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/domains/{domain}")
        return dict(obj)

    def get_file_report(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/files/{hash_value}")
        return dict(obj)

    def get_url_report(self, url: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        url_id = vt.url_id(url)
        obj = self._client.get_object(f"/urls/{url_id}")
        return dict(obj)

    def upload_file(self, file_path: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        with open(file_path, "rb") as f:
            analysis = self._client.scan_file(f, wait_for_completion=True)
        return dict(analysis)

    def get_file_behaviour(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/files/{hash_value}/behaviours")
        return dict(obj)

    def get_file_sandbox(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        obj = self._client.get_object(f"/files/{hash_value}/behaviours")
        return dict(obj)
```

---

## Task 15: Abuse.ch Connector

**Files:**
- Create: `soar/connectors/abusech/__init__.py`
- Create: `soar/connectors/abusech/abusech.py`

**Interface:**
- `_connect_impl()`: Init requests session
- `get_malware_iocs(malware: str = "") -> list[dict]`: ThreatFox IOCs
- `get_iocs_by_tag(tag: str) -> list[dict]`: IOCs by tag
- `get_iocs_by_country(country: str) -> list[dict]`: IOCs by country
- `get_feeds() -> dict`: Get available feeds
- `get_bazaar_samples(query: str = "") -> list[dict]`: MalwareBazaar samples
- `get_bazaar_file(hash: str) -> dict`: File from MalwareBazaar
- `get_urlhaus_urls(url: str = "") -> list[dict]`: URLhaus URLs
- `get_urlhaus_host(host: str) -> dict`: Host from URLhaus

- [ ] **Step 1: Create abusech/__init__.py**

```python
from soar.connectors.abusech.abusech import AbuseChConnector

__all__ = ["AbuseChConnector"]
```

- [ ] **Step 2: Create abusech/abusech.py**

```python
import requests

from soar.connectors.base import BaseConnector


class AbuseChConnector(BaseConnector):
    THREATFOX_API = "https://threatfox-api.abuse.ch/api/v1/"
    BAZAAR_API = "https://mb-api.abuse.ch/api/v1/"
    URLHAUS_API = "https://urlhaus-api.abuse.ch/v1/"

    def __init__(self, instance_name: str):
        super().__init__(instance_name)
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SOAR-Connector/1.0"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _post(self, url: str, data: dict) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(url, data=data)
        resp.raise_for_status()
        return resp.json()

    def get_malware_iocs(self, malware: str = "") -> list[dict]:
        query = {"query": "get_iocs", "malware": malware} if malware else {"query": "get_iocs"}
        data = self._post(self.THREATFOX_API, query)
        if data.get("query_status") == "no_data":
            return []
        return data.get("data", [])

    def get_iocs_by_tag(self, tag: str) -> list[dict]:
        data = self._post(self.THREATFOX_API, {"query": "taginfo", "tag": tag})
        if data.get("query_status") == "no_data":
            return []
        return data.get("data", [])

    def get_iocs_by_country(self, country: str) -> list[dict]:
        data = self._post(self.THREATFOX_API, {"query": "countryinfo", "country": country})
        if data.get("query_status") == "no_data":
            return []
        return data.get("data", [])

    def get_feeds(self) -> dict:
        data = self._post(self.THREATFOX_API, {"query": "get_feeds"})
        return data

    def get_bazaar_samples(self, query: str = "") -> list[dict]:
        data = self._post(self.BAZAAR_API, {"query": "get_recent", "selector": "100"})
        return data.get("data", [])

    def get_bazaar_file(self, hash_value: str) -> dict:
        data = self._post(self.BAZAAR_API, {"query": "get_info", "hash": hash_value})
        if data.get("query_status") == "hash_not_found":
            return {}
        items = data.get("data", [])
        return items[0] if items else {}

    def get_urlhaus_urls(self, url: str = "") -> list[dict]:
        if url:
            data = self._post(self.URLHAUS_API, {"url": url})
        else:
            data = self._post(self.URLHAUS_API, {"limit": "100"})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def get_urlhaus_host(self, host: str) -> dict:
        data = self._post(self.URLHAUS_API, {"host": host})
        return data
```

---

## Task 16: File Connector

**Files:**
- Create: `soar/connectors/file/__init__.py`
- Create: `soar/connectors/file/file.py`

**Interface:**
- `write(path: str, content: str | bytes) -> bool`: Write file
- `write_json(path: str, data: dict) -> bool`: Write JSON file
- `read(path: str) -> str`: Read file
- `read_json(path: str) -> dict`: Read JSON file
- `append(path: str, content: str) -> bool`: Append to file
- `list_files(directory: str, pattern: str = "*") -> list[str]`: List files
- `delete(path: str) -> bool`: Delete file
- `exists(path: str) -> bool`: Check file exists

- [ ] **Step 1: Create file/__init__.py**

```python
from soar.connectors.file.file import FileConnector

__all__ = ["FileConnector"]
```

- [ ] **Step 2: Create file/file.py**

```python
import json
from pathlib import Path

from soar.connectors.base import BaseConnector


class FileConnector(BaseConnector):
    def __init__(self, instance_name: str, base_path: str = "/tmp"):
        super().__init__(instance_name)
        self.base_path = Path(base_path)

    def _connect_impl(self):
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        return self.base_path / path

    def write(self, path: str, content: str | bytes) -> bool:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        target.write_text(content, encoding="utf-8") if isinstance(content, str) else target.write_bytes(content)
        return True

    def write_json(self, path: str, data: dict) -> bool:
        return self.write(path, json.dumps(data, indent=2, ensure_ascii=False))

    def read(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def read_json(self, path: str) -> dict:
        return json.loads(self.read(path))

    def append(self, path: str, content: str) -> bool:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(content)
        return True

    def list_files(self, directory: str = "", pattern: str = "*") -> list[str]:
        target = self._resolve(directory)
        if not target.exists():
            return []
        return [str(p.relative_to(self.base_path)) for p in target.glob(pattern)]

    def delete(self, path: str) -> bool:
        target = self._resolve(path)
        if target.exists():
            target.unlink()
            return True
        return False

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()
```

---

## Task 17: Update Connector Registry

**Files:**
- Modify: `soar/connectors/__init__.py`

- [ ] **Step 1: Verify all connectors are discoverable**

Run: `python -c "from soar.connectors import ConnectorRegistry; r = ConnectorRegistry(); r._discover_classes(); print(list(r._classes.keys()))"`

Expected: List of all connector types.

---

## Task 18: Run Verification

- [ ] **Step 1: Run lint**

```bash
ruff check soar/connectors/
```

- [ ] **Step 2: Run type check**

```bash
mypy soar/connectors/ --ignore-missing-imports
```

- [ ] **Step 3: Run existing tests**

```bash
python -m pytest tests/ -v
```

---

## Execution Handoff

After saving the plan, determine execution approach:

1. **Check memory** for a saved `execution-style` preference in the `compose-preferences` memory file. If found (`subagent` or `inline`), use it and skip to the handler below.

2. **If no saved preference,** ask through `compose:ask`:
   - header: `Execution`
   - question: `Plan saved. How would you like to execute it?`
   - options:
     - label: `Subagent, always`, description: `Fresh subagent per task — remember for future sessions`
     - label: `Subagent, this time`, description: `Fresh subagent per task — just this once`
     - label: `Inline, always`, description: `Execute in this session — remember for future sessions`
     - label: `Inline, this time`, description: `Execute in this session — just this once`

   If no user is available, default to Inline for ≤ 3 tasks or tightly coupled tasks, Subagent for > 3 independent tasks.

3. **If "always" variant:** Save to the `compose-preferences` memory file as `execution-style: subagent` or `execution-style: inline`.

**If Subagent:** Use compose:subagent — fresh subagent per task + two-stage review.

**If Inline:** Use compose:execute — batch execution with checkpoints
