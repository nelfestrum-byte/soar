# New SOAR Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 10 new enterprise connectors to the SOAR platform: WinRM, SMB+RPC, Shodan, Censys, Fofa, URLhaus, Kaspersky OpenTip, MISP, RstCloud, crt.sh

**Architecture:** Each connector follows the established pattern: snake_case directory, `BaseConnector` subclass, lazy `_connect_impl()`, `disconnect()` cleanup, `.example.yml` config template. API-key connectors use `requests.Session`; connection-based connectors use specialized libraries.

**Tech Stack:** Python 3.11+, requests, pywinrm, impacket, shodan, pymisp, BaseConnector pattern

---

## Connector Summary

| # | Connector | Type | Auth | Library |
|---|-----------|------|------|---------|
| 1 | WinRM | Connection | host/port/user/pass | pywinrm |
| 2 | SMB+RPC | Connection | host/port/user/pass/domain | impacket |
| 3 | Shodan | API-Key | api_key | shodan |
| 4 | Censys | API-Key | api_id + api_secret | requests |
| 5 | Fofa | API-Key | email + api_key | requests |
| 6 | URLhaus | Free API | none | requests |
| 7 | Kaspersky OpenTip | API-Key | api_key | requests |
| 8 | MISP | API-Key | url + api_key + verify_ssl | pymisp |
| 9 | RstCloud | API-Key | api_key | requests |
| 10 | crt.sh | Free API | none | requests |

---

### Task 1: WinRM Connector

**Covers:** Windows remote management — execute commands, upload/download files on Windows hosts via WinRM

**Files:**
- Create: `soar/connectors/winrm/__init__.py`
- Create: `soar/connectors/winrm/winrm.py`
- Create: `soar/connectors/winrm/winrm.example.yml`
- Test: `tests/soar/test_winrm_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.winrm.winrm import WinRMConnector


def test_winrm_init():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    assert conn.instance_name == "test_winrm"
    assert conn.host == "10.0.0.1"
    assert conn.port == 5985
    assert conn.transport == "ntlm"
    assert conn.is_connected is False


def test_winrm_connect_impl():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Client") as mock_client:
        conn._connect_impl()
        mock_client.assert_called_once_with(
            "http://10.0.0.1:5985/wsman",
            auth=("admin", "pass"),
            transport="ntlm",
            server_cert_validation="ignore",
        )
        assert conn.is_connected is False  # _connect_impl doesn't set _connected


def test_winrm_exec_command():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Client") as mock_client:
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.std_out = "output"
        mock_run.std_err = "error"
        mock_run.status_code = 0
        mock_session.run.return_value = mock_run
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.exec_command("whoami")
        assert result == {"stdout": "output", "stderr": "error", "exit_code": 0}
        mock_session.run.assert_called_once_with("whoami", timeout=30)


def test_winrm_exec_command_with_timeout():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Client") as mock_client:
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.std_out = ""
        mock_run.std_err = ""
        mock_run.status_code = 0
        mock_session.run.return_value = mock_run
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        conn.exec_command("dir", timeout=60)
        mock_session.run.assert_called_once_with("dir", timeout=60)


def test_winrm_upload_file():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Client") as mock_client:
        mock_session = MagicMock()
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.upload_file("/local/file.txt", "C:\\remote\\file.txt")
        assert result is True
        mock_session.upload.assert_called_once_with("C:\\remote\\file.txt", "/local/file.txt")


def test_winrm_download_file():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Client") as mock_client:
        mock_session = MagicMock()
        mock_client.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.download_file("C:\\remote\\file.txt", "/local/file.txt")
        assert result is True
        mock_session.download.assert_called_once_with("C:\\remote\\file.txt", "/local/file.txt")


def test_winrm_disconnect():
    conn = WinRMConnector(
        instance_name="test_winrm",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.winrm.winrm.winrm.Client"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._client is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_winrm_connector.py -v`
Expected: FAIL with import error (module not found)

- [ ] **Step 3: Write implementation**

`soar/connectors/winrm/__init__.py`:
```python
from soar.connectors.winrm.winrm import WinRMConnector

__all__ = ["WinRMConnector"]
```

`soar/connectors/winrm/winrm.py`:
```python
import winrm

from soar.connectors.base import BaseConnector


class WinRMConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 5985,
        username: str = "",
        password: str = "",
        transport: str = "ntlm",
        verify_ssl: bool = False,
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.transport = transport
        self.verify_ssl = verify_ssl
        self._client: winrm.Session | None = None

    def _connect_impl(self):
        scheme = "https" if self.verify_ssl else "http"
        endpoint = f"{scheme}://{self.host}:{self.port}/wsman"
        self._client = winrm.Session(
            endpoint,
            auth=(self.username, self.password),
            transport=self.transport,
            server_cert_validation="ignore" if not self.verify_ssl else "validate",
        )

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def exec_command(self, command: str, timeout: int = 30) -> dict:
        self._ensure_connected()
        assert self._client is not None
        r = self._client.run(command, timeout=timeout)
        return {
            "stdout": r.std_out,
            "stderr": r.std_err,
            "exit_code": r.status_code,
        }

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        self._client.upload(remote_path, local_path)
        return True

    def download_file(self, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        self._client.download(remote_path, local_path)
        return True

    def run_ps(self, script: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        r = self._client.run_ps(script)
        return {
            "stdout": r.std_out,
            "stderr": r.std_err,
            "exit_code": r.status_code,
        }
```

`soar/connectors/winrm/winrm.example.yml`:
```yaml
instances:
  winrm_prod:
    host: 10.0.0.50
    port: 5985
    username: Administrator
    password: YOUR_PASSWORD
    transport: ntlm
    verify_ssl: false
  winrm_https:
    host: 10.0.0.51
    port: 5986
    username: Administrator
    password: YOUR_PASSWORD
    transport: ntlm
    verify_ssl: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_winrm_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/winrm/ tests/soar/test_winrm_connector.py
git commit -m "feat: add WinRM connector for Windows remote management"
```

---

### Task 2: SMB+RPC Connector

**Covers:** Windows SMB/RPC remote operations — file listing, upload, download, service management via SMB

**Files:**
- Create: `soar/connectors/smb_rpc/__init__.py`
- Create: `soar/connectors/smb_rpc/smb_rpc.py`
- Create: `soar/connectors/smb_rpc/smb_rpc.example.yml`
- Test: `tests/soar/test_smb_rpc_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch, call
from soar.connectors.smb_rpc.smb_rpc import SMBRPCConnector


def test_smb_rpc_init():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
        domain="WORKGROUP",
    )
    assert conn.instance_name == "test_smb"
    assert conn.host == "10.0.0.1"
    assert conn.port == 445
    assert conn.domain == "WORKGROUP"
    assert conn.is_connected is False


def test_smb_rpc_connect_impl():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.SMBConnection") as mock_smb:
        conn._connect_impl()
        mock_smb.assert_called_once_with("*", "10.0.0.1", sess_port=445)
        mock_smb.return_value.login.assert_called_once_with("admin", "pass", "", "", "")


def test_smb_rpc_list_shares():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.SMBConnection") as mock_smb:
        mock_conn = MagicMock()
        mock_conn.listShares.return_value = [
            {"Name": "C$", "Type": 0x80000000},
            {"Name": "IPC$", "Type": 0x80000003},
        ]
        mock_smb.return_value = mock_conn
        conn._connect_impl()
        conn._connected = True

        shares = conn.list_shares()
        assert len(shares) == 2
        assert shares[0]["Name"] == "C$"


def test_smb_rpc_list_files():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.SMBConnection") as mock_smb:
        mock_conn = MagicMock()
        mock_conn.listPath.return_value = [
            {"filename": "test.txt", "file_size": 100, "is_directory": False},
            {"filename": "subdir", "file_size": 0, "is_directory": True},
        ]
        mock_smb.return_value = mock_conn
        conn._connect_impl()
        conn._connected = True

        files = conn.list_files("C$", "Users\\Admin")
        assert len(files) == 2
        assert files[0]["filename"] == "test.txt"
        mock_conn.listPath.assert_called_once_with("C$", "Users\\Admin")


def test_smb_rpc_upload_file():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.SMBConnection") as mock_smb:
        mock_conn = MagicMock()
        mock_smb.return_value = mock_conn
        conn._connect_impl()
        conn._connected = True

        with patch("builtins.open", MagicMock()):
            result = conn.upload_file("C$", "remote.txt", "/local/file.txt")
        assert result is True


def test_smb_rpc_download_file():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.SMBConnection") as mock_smb:
        mock_conn = MagicMock()
        mock_smb.return_value = mock_conn
        conn._connect_impl()
        conn._connected = True

        with patch("builtins.open", MagicMock()):
            result = conn.download_file("C$", "remote.txt", "/local/file.txt")
        assert result is True


def test_smb_rpc_delete_file():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.SMBConnection") as mock_smb:
        mock_conn = MagicMock()
        mock_smb.return_value = mock_conn
        conn._connect_impl()
        conn._connected = True

        result = conn.delete_file("C$", "Users\\Admin\\file.txt")
        assert result is True


def test_smb_rpc_disconnect():
    conn = SMBRPCConnector(
        instance_name="test_smb",
        host="10.0.0.1",
        username="admin",
        password="pass",
    )
    with patch("soar.connectors.smb_rpc.smb_rpc.SMBConnection"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._client is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_smb_rpc_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/smb_rpc/__init__.py`:
```python
from soar.connectors.smb_rpc.smb_rpc import SMBRPCConnector

__all__ = ["SMBRPCConnector"]
```

`soar/connectors/smb_rpc/smb_rpc.py`:
```python
from impacket.smbconnection import SMBConnection

from soar.connectors.base import BaseConnector


class SMBRPCConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        host: str,
        port: int = 445,
        username: str = "",
        password: str = "",
        domain: str = "",
        lmhash: str = "",
        nthash: str = "",
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.domain = domain
        self.lmhash = lmhash
        self.nthash = nthash
        self._client: SMBConnection | None = None

    def _connect_impl(self):
        self._client = SMBConnection("*", self.host, sess_port=self.port)
        self._client.login(self.username, self.password, self.domain, self.lmhash, self.nthash)

    def disconnect(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def list_shares(self) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        shares = self._client.listShares()
        result = []
        for s in shares:
            entry = {
                "name": s["Name"],
                "type": s["Type"],
                "remark": s["Remark"].decode("utf-8", errors="replace") if isinstance(s["Remark"], bytes) else s["Remark"],
            }
            result.append(entry)
        return result

    def list_files(self, share: str, path: str = "") -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        files = self._client.listPath(share, path)
        return [
            {
                "filename": f["filename"],
                "file_size": f["file_size"],
                "is_directory": bool(f["is_directory"]),
                "create_time": f["create_time"],
                "last_access_time": f["last_access_time"],
                "last_write_time": f["last_write_time"],
            }
            for f in files
            if f["filename"] not in (".", "..")
        ]

    def upload_file(self, share: str, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        with open(local_path, "rb") as f:
            self._client.putFile(share, remote_path, f.read)
        return True

    def download_file(self, share: str, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        with open(local_path, "wb") as f:
            self._client.getFile(share, remote_path, f.write)
        return True

    def delete_file(self, share: str, path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        self._client.deleteFile(share, path)
        return True

    def create_directory(self, share: str, path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        self._client.createDirectory(share, path)
        return True

    def check_file_exists(self, share: str, path: str) -> bool:
        self._ensure_connected()
        assert self._client is not None
        try:
            self._client.getAttributes(share, path)
            return True
        except Exception:
            return False
```

`soar/connectors/smb_rpc/smb_rpc.example.yml`:
```yaml
instances:
  smb_fileserver:
    host: 10.0.0.20
    port: 445
    username: admin
    password: YOUR_PASSWORD
    domain: WORKGROUP
  smb_domain_admin:
    host: 10.0.0.21
    port: 445
    username: administrator
    password: YOUR_PASSWORD
    domain: CORP
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_smb_rpc_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/smb_rpc/ tests/soar/test_smb_rpc_connector.py
git commit -m "feat: add SMB+RPC connector for Windows file sharing"
```

---

### Task 3: Shodan Connector

**Covers:** Internet asset discovery — search hosts, get IP info, DNS resolution, network alerts

**Files:**
- Create: `soar/connectors/shodan/__init__.py`
- Create: `soar/connectors/shodan/shodan.py`
- Create: `soar/connectors/shodan/shodan.example.yml`
- Test: `tests/soar/test_shodan_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.shodan.shodan import ShodanConnector


def test_shodan_init():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    assert conn.instance_name == "test_shodan"
    assert conn.api_key == "TEST_KEY"
    assert conn.is_connected is False


def test_shodan_connect_impl():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan") as mock_cls:
        conn._connect_impl()
        mock_cls.assert_called_once_with("TEST_KEY")


def test_shodan_search():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan") as mock_cls:
        mock_api = MagicMock()
        mock_api.search.return_value = {"matches": [{"ip_str": "1.2.3.4"}], "total": 1}
        mock_cls.return_value = mock_api
        conn._connect_impl()
        conn._connected = True

        result = conn.search("apache")
        assert result["total"] == 1
        mock_api.search.assert_called_once_with("apache")


def test_shodan_search_with_filters():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan") as mock_cls:
        mock_api = MagicMock()
        mock_api.search.return_value = {"matches": [], "total": 0}
        mock_cls.return_value = mock_api
        conn._connect_impl()
        conn._connected = True

        conn.search("apache", page=2, limit=50)
        mock_api.search.assert_called_once_with("apache", page=2, limit=50)


def test_shodan_host_info():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan") as mock_cls:
        mock_api = MagicMock()
        mock_api.host.return_value = {"ip_str": "8.8.8.8", "ports": [53, 443]}
        mock_cls.return_value = mock_api
        conn._connect_impl()
        conn._connected = True

        result = conn.host_info("8.8.8.8")
        assert result["ip_str"] == "8.8.8.8"
        mock_api.host.assert_called_once_with("8.8.8.8")


def test_shodan_dns_resolve():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan") as mock_cls:
        mock_api = MagicMock()
        mock_api.dns.resolve.return_value = [{"domain": "example.com", "data": "93.184.216.34"}]
        mock_cls.return_value = mock_api
        conn._connect_impl()
        conn._connected = True

        result = conn.dns_resolve("example.com")
        assert len(result) == 1


def test_shodan_reverse_dns():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan") as mock_cls:
        mock_api = MagicMock()
        mock_api.dns.reverse.return_value = ["example.com"]
        mock_cls.return_value = mock_api
        conn._connect_impl()
        conn._connected = True

        result = conn.reverse_dns("93.184.216.34")
        assert result == ["example.com"]


def test_shodan_disconnect():
    conn = ShodanConnector(instance_name="test_shodan", api_key="TEST_KEY")
    with patch("soar.connectors.shodan.shodan.shodan.Shodan"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._client is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_shodan_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/shodan/__init__.py`:
```python
from soar.connectors.shodan.shodan import ShodanConnector

__all__ = ["ShodanConnector"]
```

`soar/connectors/shodan/shodan.py`:
```python
import shodan

from soar.connectors.base import BaseConnector


class ShodanConnector(BaseConnector):
    def __init__(self, instance_name: str, api_key: str):
        super().__init__(instance_name)
        self.api_key = api_key
        self._client: shodan.Shodan | None = None

    def _connect_impl(self):
        self._client = shodan.Shodan(self.api_key)

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def search(self, query: str, page: int = 1, limit: int = 100) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.search(query, page=page, limit=limit)

    def host_info(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.host(ip)

    def dns_resolve(self, hostnames: str) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        return self._client.dns.resolve(hostnames)

    def reverse_dns(self, ips: str) -> list[str]:
        self._ensure_connected()
        assert self._client is not None
        return self._client.dns.reverse(ips)

    def get_my_ip(self) -> str:
        self._ensure_connected()
        assert self._client is not None
        return self._client.tools.myip()

    def get_network_alerts(self, netblock: str) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        return self._client.network_alerts.query(netblock)

    def get_services(self) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.services
```

`soar/connectors/shodan/shodan.example.yml`:
```yaml
instances:
  shodan_main:
    api_key: YOUR_SHODAN_API_KEY
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_shodan_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/shodan/ tests/soar/test_shodan_connector.py
git commit -m "feat: add Shodan connector for internet asset discovery"
```

---

### Task 4: Censys Connector

**Covers:** Internet asset discovery — search hosts, certificates, get host details

**Files:**
- Create: `soar/connectors/censys/__init__.py`
- Create: `soar/connectors/censys/censys.py`
- Create: `soar/connectors/censys/censys.example.yml`
- Test: `tests/soar/test_censys_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.censys.censys import CensysConnector


def test_censys_init():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="TEST_ID",
        api_secret="TEST_SECRET",
    )
    assert conn.instance_name == "test_censys"
    assert conn.api_id == "TEST_ID"
    assert conn.base_url == "https://search.censys.io/api"
    assert conn.is_connected is False


def test_censys_connect_impl():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="TEST_ID",
        api_secret="TEST_SECRET",
    )
    with patch("soar.connectors.censys.censys.requests.Session") as mock_session:
        conn._connect_impl()
        mock_session.assert_called_once()
        assert conn._session is not None


def test_censys_search_hosts():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="TEST_ID",
        api_secret="TEST_SECRET",
    )
    with patch("soar.connectors.censys.censys.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [{"ip": "1.2.3.4"}], "total": 1}
        mock_resp.raise_for_status = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.search_hosts("services.http.title: Apache")
        assert result["total"] == 1


def test_censys_get_host():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="TEST_ID",
        api_secret="TEST_SECRET",
    )
    with patch("soar.connectors.censys.censys.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ip": "1.2.3.4", "services": []}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.get_host("1.2.3.4")
        assert result["ip"] == "1.2.3.4"


def test_censys_search_certificates():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="TEST_ID",
        api_secret="TEST_SECRET",
    )
    with patch("soar.connectors.censys.censys.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hits": [], "total": 0}
        mock_resp.raise_for_status = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.search_certificates("parsed.subject.common_name: example.com")
        assert result["total"] == 0


def test_censys_disconnect():
    conn = CensysConnector(
        instance_name="test_censys",
        api_id="TEST_ID",
        api_secret="TEST_SECRET",
    )
    with patch("soar.connectors.censys.censys.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_censys_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/censys/__init__.py`:
```python
from soar.connectors.censys.censys import CensysConnector

__all__ = ["CensysConnector"]
```

`soar/connectors/censys/censys.py`:
```python
import requests
from requests.auth import HTTPBasicAuth

from soar.connectors.base import BaseConnector


class CensysConnector(BaseConnector):
    BASE_URL = "https://search.censys.io/api"

    def __init__(
        self,
        instance_name: str,
        api_id: str,
        api_secret: str,
        base_url: str = "",
    ):
        super().__init__(instance_name)
        self.api_id = api_id
        self.api_secret = api_secret
        self.base_url = base_url or self.BASE_URL
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(self.api_id, self.api_secret)
        self._session.headers["Accept"] = "application/json"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def search_hosts(self, query: str, page: int = 1, per_page: int = 100) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(
            f"{self.base_url}/v2/hosts/search",
            json={"q": query, "page": page, "per_page": per_page},
        )
        resp.raise_for_status()
        return resp.json()

    def get_host(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self.base_url}/v2/hosts/{ip}")
        resp.raise_for_status()
        return resp.json()

    def search_certificates(self, query: str, page: int = 1, per_page: int = 100) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(
            f"{self.base_url}/v1/search/certificates",
            json={"q": query, "page": page, "per_page": per_page},
        )
        resp.raise_for_status()
        return resp.json()

    def get_certificate(self, fingerprint: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(f"{self.base_url}/v1/certificates/{fingerprint}")
        resp.raise_for_status()
        return resp.json()
```

`soar/connectors/censys/censys.example.yml`:
```yaml
instances:
  censys_main:
    api_id: YOUR_CENSYS_API_ID
    api_secret: YOUR_CENSYS_API_SECRET
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_censys_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/censys/ tests/soar/test_censys_connector.py
git commit -m "feat: add Censys connector for internet asset discovery"
```

---

### Task 5: Fofa Connector

**Covers:** Internet asset search — query hosts, get host details, batch queries

**Files:**
- Create: `soar/connectors/fofa/__init__.py`
- Create: `soar/connectors/fofa/fofa.py`
- Create: `soar/connectors/fofa/fofa.example.yml`
- Test: `tests/soar/test_fofa_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.fofa.fofa import FofaConnector


def test_fofa_init():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="TEST_KEY",
    )
    assert conn.instance_name == "test_fofa"
    assert conn.email == "test@example.com"
    assert conn.base_url == "https://fofa.info/api/v1"
    assert conn.is_connected is False


def test_fofa_connect_impl():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.fofa.fofa.requests.Session") as mock_session:
        conn._connect_impl()
        mock_session.assert_called_once()


def test_fofa_search():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.fofa.fofa.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [["1.2.3.4", "80", "Apache"]],
            "size": 1,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.search('title="Apache"')
        assert result["size"] == 1


def test_fofa_search_with_fields():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.fofa.fofa.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [], "size": 0}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        conn.search('title="test"', fields="ip,port,title", size=50)
        mock_session.get.assert_called_once()


def test_fofa_get_host_info():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.fofa.fofa.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ip": "1.2.3.4", "ports": ["80/tcp"]}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.get_host_info("1.2.3.4")
        assert result["ip"] == "1.2.3.4"


def test_fofa_disconnect():
    conn = FofaConnector(
        instance_name="test_fofa",
        email="test@example.com",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.fofa.fofa.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_fofa_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/fofa/__init__.py`:
```python
from soar.connectors.fofa.fofa import FofaConnector

__all__ = ["FofaConnector"]
```

`soar/connectors/fofa/fofa.py`:
```python
import base64

import requests

from soar.connectors.base import BaseConnector


class FofaConnector(BaseConnector):
    BASE_URL = "https://fofa.info/api/v1"

    def __init__(
        self,
        instance_name: str,
        email: str,
        api_key: str,
        base_url: str = "",
    ):
        super().__init__(instance_name)
        self.email = email
        self.api_key = api_key
        self.base_url = base_url or self.BASE_URL
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _query_base64(self, query: str) -> str:
        return base64.b64encode(query.encode()).decode()

    def search(
        self,
        query: str,
        fields: str = "ip,port,protocol,host",
        size: int = 100,
        page: int = 1,
    ) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/search/all",
            params={
                "email": self.email,
                "key": self.api_key,
                "qbase64": self._query_base64(query),
                "fields": fields,
                "size": size,
                "page": page,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def get_host_info(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/host/detail",
            params={"email": self.email, "key": self.api_key, "ips": ip},
        )
        resp.raise_for_status()
        return resp.json()

    def get_user_info(self) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/info/my",
            params={"email": self.email, "key": self.api_key},
        )
        resp.raise_for_status()
        return resp.json()
```

`soar/connectors/fofa/fofa.example.yml`:
```yaml
instances:
  fofa_main:
    email: your@email.com
    api_key: YOUR_FOFA_API_KEY
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_fofa_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/fofa/ tests/soar/test_fofa_connector.py
git commit -m "feat: add Fofa connector for internet asset search"
```

---

### Task 6: URLhaus Connector

**Covers:** Malware URL intelligence — search URLs, get URL details, check payloads, tag-based queries

**Files:**
- Create: `soar/connectors/urlhaus/__init__.py`
- Create: `soar/connectors/urlhaus/urlhaus.py`
- Create: `soar/connectors/urlhaus/urlhaus.example.yml`
- Test: `tests/soar/test_urlhaus_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.urlhaus.urlhaus import URLhausConnector


def test_urlhaus_init():
    conn = URLhausConnector(instance_name="test_urlhaus")
    assert conn.instance_name == "test_urlhaus"
    assert conn.base_url == "https://urlhaus-api.abuse.ch/v1"
    assert conn.is_connected is False


def test_urlhaus_connect_impl():
    conn = URLhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session") as mock_session:
        conn._connect_impl()
        mock_session.assert_called_once()
        assert conn._session is not None


def test_urlhaus_get_url_info():
    conn = URLhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "query_status": "ok",
            "urls": [{"url": "http://evil.com/mal.exe", "threat": "malware_download"}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.get_url_info("http://evil.com/mal.exe")
        assert len(result) == 1
        assert result[0]["threat"] == "malware_download"


def test_urlhaus_get_host_info():
    conn = URLhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "query_status": "ok",
            "urls": [{"url": "http://evil.com/bad.exe"}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.get_host_info("evil.com")
        assert len(result) == 1


def test_urlhaus_get_payload_info():
    conn = URLhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "query_status": "ok",
            "md5_hash": "abc123",
            "file_type": "exe",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.get_payload_info("abc123def456")
        assert result["md5_hash"] == "abc123"


def test_urlhaus_get_recent_urls():
    conn = URLhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "query_status": "ok",
            "urls": [{"url": "http://bad.com/1"}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.get_recent_urls(limit=50)
        assert len(result) == 1


def test_urlhaus_url_exists():
    conn = URLhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"query_status": "no_results"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.url_exists("http://safe.com")
        assert result is False


def test_urlhaus_disconnect():
    conn = URLhausConnector(instance_name="test_urlhaus")
    with patch("soar.connectors.urlhaus.urlhaus.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_urlhaus_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/urlhaus/__init__.py`:
```python
from soar.connectors.urlhaus.urlhaus import URLhausConnector

__all__ = ["URLhausConnector"]
```

`soar/connectors/urlhaus/urlhaus.py`:
```python
import requests

from soar.connectors.base import BaseConnector


class URLhausConnector(BaseConnector):
    BASE_URL = "https://urlhaus-api.abuse.ch/v1"

    def __init__(self, instance_name: str, base_url: str = ""):
        super().__init__(instance_name)
        self.base_url = base_url or self.BASE_URL
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/x-www-form-urlencoded"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def _post(self, data: dict) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.post(f"{self.base_url}/url/", data=data)
        resp.raise_for_status()
        return resp.json()

    def get_url_info(self, url: str) -> list[dict]:
        data = self._post({"url": url})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def get_host_info(self, host: str) -> list[dict]:
        data = self._post({"host": host})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def get_payload_info(self, hash_value: str) -> dict:
        data = self._post({"query": "get_payload", "hash": hash_value})
        if data.get("query_status") == "no_results":
            return {}
        return data

    def get_recent_urls(self, limit: int = 100) -> list[dict]:
        data = self._post({"limit": str(limit)})
        if data.get("query_status") == "no_results":
            return []
        return data.get("urls", [])

    def url_exists(self, url: str) -> bool:
        data = self._post({"url": url})
        return data.get("query_status") != "no_results"

    def tag_url(self, url: str, tag: str, threat: str = "malware_download") -> dict:
        data = self._post({
            "url": url,
            "threat": threat,
            "tag": tag,
        })
        return data
```

`soar/connectors/urlhaus/urlhaus.example.yml`:
```yaml
instances:
  urlhaus_main: {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_urlhaus_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/urlhaus/ tests/soar/test_urlhaus_connector.py
git commit -m "feat: add URLhaus connector for malware URL intelligence"
```

---

### Task 7: Kaspersky OpenTip Connector

**Covers:** Threat intelligence — IP/domain/hash/URL lookups, IOC enrichment, threat reports

**Files:**
- Create: `soar/connectors/kaspersky_opentip/__init__.py`
- Create: `soar/connectors/kaspersky_opentip/kaspersky_opentip.py`
- Create: `soar/connectors/kaspersky_opentip/kaspersky_opentip.example.yml`
- Test: `tests/soar/test_kaspersky_opentip_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.kaspersky_opentip.kaspersky_opentip import KasperskyOpenTipConnector


def test_kaspersky_opentip_init():
    conn = KasperskyOpenTipConnector(
        instance_name="test_otip",
        api_key="TEST_KEY",
    )
    assert conn.instance_name == "test_otip"
    assert conn.api_key == "TEST_KEY"
    assert conn.base_url == "https://opentip.kaspersky.com"
    assert conn.is_connected is False


def test_kaspersky_opentip_connect_impl():
    conn = KasperskyOpenTipConnector(
        instance_name="test_otip",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.kaspersky_opentip.kaspersky_opentip.requests.Session") as mock_session:
        conn._connect_impl()
        mock_session.assert_called_once()
        assert conn._session is not None


def test_kaspersky_opentip_check_ip():
    conn = KasperskyOpenTipConnector(
        instance_name="test_otip",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.kaspersky_opentip.kaspersky_opentip.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ip": "8.8.8.8", "verdict": "Whitelist"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_ip("8.8.8.8")
        assert result["verdict"] == "Whitelist"


def test_kaspersky_opentip_check_domain():
    conn = KasperskyOpenTipConnector(
        instance_name="test_otip",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.kaspersky_opentip.kaspersky_opentip.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"domain": "example.com", "verdict": "Whitelist"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_domain("example.com")
        assert result["verdict"] == "Whitelist"


def test_kaspersky_opentip_check_url():
    conn = KasperskyOpenTipConnector(
        instance_name="test_otip",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.kaspersky_opentip.kaspersky_opentip.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"url": "http://example.com", "verdict": "Whitelist"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_url("http://example.com")
        assert result["verdict"] == "Whitelist"


def test_kaspersky_opentip_check_hash():
    conn = KasperskyOpenTipConnector(
        instance_name="test_otip",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.kaspersky_opentip.kaspersky_opentip.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"sha256": "abc123", "verdict": "Malware"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_hash("abc123def456")
        assert result["verdict"] == "Malware"


def test_kaspersky_opentip_disconnect():
    conn = KasperskyOpenTipConnector(
        instance_name="test_otip",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.kaspersky_opentip.kaspersky_opentip.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_kaspersky_opentip_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/kaspersky_opentip/__init__.py`:
```python
from soar.connectors.kaspersky_opentip.kaspersky_opentip import KasperskyOpenTipConnector

__all__ = ["KasperskyOpenTipConnector"]
```

`soar/connectors/kaspersky_opentip/kaspersky_opentip.py`:
```python
import requests

from soar.connectors.base import BaseConnector


class KasperskyOpenTipConnector(BaseConnector):
    BASE_URL = "https://opentip.kaspersky.com"

    def __init__(
        self,
        instance_name: str,
        api_key: str,
        base_url: str = "",
        verify_ssl: bool = True,
    ):
        super().__init__(instance_name)
        self.api_key = api_key
        self.base_url = base_url or self.BASE_URL
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["X-Api-Key"] = self.api_key
        self._session.headers["Accept"] = "application/json"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def check_ip(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/ip/{ip}",
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def check_domain(self, domain: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/domain/{domain}",
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def check_url(self, url: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/url",
            params={"url": url},
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def check_hash(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/file/{hash_value}",
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()
```

`soar/connectors/kaspersky_opentip/kaspersky_opentip.example.yml`:
```yaml
instances:
  opentip_main:
    api_key: YOUR_KASPERSKY_OPENTIP_API_KEY
    verify_ssl: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_kaspersky_opentip_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/kaspersky_opentip/ tests/soar/test_kaspersky_opentip_connector.py
git commit -m "feat: add Kaspersky OpenTip connector for threat intelligence"
```

---

### Task 8: MISP Connector

**Covers:** Threat intelligence platform — events, attributes, sightings, taxonomies, export

**Files:**
- Create: `soar/connectors/misp/__init__.py`
- Create: `soar/connectors/misp/misp.py`
- Create: `soar/connectors/misp/misp.example.yml`
- Test: `tests/soar/test_misp_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.misp.misp import MISPConnector


def test_misp_init():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    assert conn.instance_name == "test_misp"
    assert conn.url == "https://misp.local"
    assert conn.api_key == "TEST_KEY"
    assert conn.verify_ssl is True
    assert conn.is_connected is False


def test_misp_connect_impl():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp:
        conn._connect_impl()
        mock_misp.assert_called_once_with("https://misp.local", "TEST_KEY", ssl=True)


def test_misp_connect_impl_no_ssl():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
        verify_ssl=False,
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp:
        conn._connect_impl()
        mock_misp.assert_called_once_with("https://misp.local", "TEST_KEY", ssl=False)


def test_misp_search_events():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp_cls:
        mock_misp = MagicMock()
        mock_misp.search.return_value = {"response": [{"Event": {"id": "1", "info": "Test"}}]}
        mock_misp_cls.return_value = mock_misp
        conn._connect_impl()
        conn._connected = True

        result = conn.search_events("malware")
        assert len(result) == 1
        assert result[0]["Event"]["info"] == "Test"


def test_misp_get_event():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp_cls:
        mock_misp = MagicMock()
        mock_misp.get_event.return_value = {"Event": {"id": "1"}}
        mock_misp_cls.return_value = mock_misp
        conn._connect_impl()
        conn._connected = True

        result = conn.get_event("1")
        assert result["Event"]["id"] == "1"


def test_misp_get_attribute():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp_cls:
        mock_misp = MagicMock()
        mock_misp.get_attribute.return_value = {"Attribute": {"id": "1", "type": "ip-dst"}}
        mock_misp_cls.return_value = mock_misp
        conn._connect_impl()
        conn._connected = True

        result = conn.get_attribute("1")
        assert result["Attribute"]["type"] == "ip-dst"


def test_misp_search_attributes():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp_cls:
        mock_misp = MagicMock()
        mock_misp.search.return_value = {"response": [{"Attribute": {"value": "1.2.3.4"}}]}
        mock_misp_cls.return_value = mock_misp
        conn._connect_impl()
        conn._connected = True

        result = conn.search_attributes(value="1.2.3.4")
        assert len(result) == 1


def test_misp_add_attribute():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp_cls:
        mock_misp = MagicMock()
        mock_misp.add_attribute.return_value = {"Attribute": {"id": "2"}}
        mock_misp_cls.return_value = mock_misp
        conn._connect_impl()
        conn._connected = True

        result = conn.add_attribute("1", type="ip-dst", value="1.2.3.4")
        assert result["Attribute"]["id"] == "2"


def test_misp_get_sightings():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP") as mock_misp_cls:
        mock_misp = MagicMock()
        mock_misp.sighting_list.return_value = [{"Sighting": {"id": "1"}}]
        mock_misp_cls.return_value = mock_misp
        conn._connect_impl()
        conn._connected = True

        result = conn.get_sightings("1")
        assert len(result) == 1


def test_misp_disconnect():
    conn = MISPConnector(
        instance_name="test_misp",
        url="https://misp.local",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.misp.misp.pymisp.ExpandedPyMISP"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._client is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_misp_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/misp/__init__.py`:
```python
from soar.connectors.misp.misp import MISPConnector

__all__ = ["MISPConnector"]
```

`soar/connectors/misp/misp.py`:
```python
from pymisp import ExpandedPyMISP

from soar.connectors.base import BaseConnector


class MISPConnector(BaseConnector):
    def __init__(
        self,
        instance_name: str,
        url: str,
        api_key: str,
        verify_ssl: bool = True,
    ):
        super().__init__(instance_name)
        self.url = url
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self._client: ExpandedPyMISP | None = None

    def _connect_impl(self):
        self._client = ExpandedPyMISP(self.url, self.api_key, ssl=self.verify_ssl)

    def disconnect(self):
        if self._client:
            self._client = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def search_events(self, keyword: str, **kwargs) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.search(value=keyword, **kwargs)
        return result.get("response", [])

    def get_event(self, event_id: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.get_event(event_id)

    def add_event(self, event_dict: dict) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.add_event(event_dict)

    def delete_event(self, event_id: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.delete_event(event_id)

    def search_attributes(self, **kwargs) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        result = self._client.search(value=kwargs.pop("value", None), type_attribute=kwargs.pop("type", None), **kwargs)
        return result.get("response", [])

    def get_attribute(self, attribute_id: str) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.get_attribute(attribute_id)

    def add_attribute(self, event_id: str, **kwargs) -> dict:
        self._ensure_connected()
        assert self._client is not None
        return self._client.add_attribute(event_id, **kwargs)

    def get_sightings(self, attribute_id: str) -> list[dict]:
        self._ensure_connected()
        assert self._client is not None
        return self._client.sighting_list(attribute_id)

    def add_sighting(self, attribute_id: str, source: str = "") -> dict:
        self._ensure_connected()
        assert self._client is not None
        sighting = {"attribute_id": attribute_id, "source": source}
        return self._client.sighting_add(sighting)
```

`soar/connectors/misp/misp.example.yml`:
```yaml
instances:
  misp_main:
    url: https://misp.local
    api_key: YOUR_MISP_API_KEY
    verify_ssl: true
  misp_dev:
    url: https://misp-dev.local
    api_key: YOUR_MISP_DEV_API_KEY
    verify_ssl: false
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_misp_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/misp/ tests/soar/test_misp_connector.py
git commit -m "feat: add MISP connector for threat intelligence platform"
```

---

### Task 9: RstCloud Connector

**Covers:** Threat intelligence — IP/domain/hash reputation, threat reports, IOC lookups

**Files:**
- Create: `soar/connectors/rstcloud/__init__.py`
- Create: `soar/connectors/rstcloud/rstcloud.py`
- Create: `soar/connectors/rstcloud/rstcloud.example.yml`
- Test: `tests/soar/test_rstcloud_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.rstcloud.rstcloud import RstCloudConnector


def test_rstcloud_init():
    conn = RstCloudConnector(
        instance_name="test_rstcloud",
        api_key="TEST_KEY",
    )
    assert conn.instance_name == "test_rstcloud"
    assert conn.api_key == "TEST_KEY"
    assert conn.base_url == "https://opentip.rstcloud.net"
    assert conn.is_connected is False


def test_rstcloud_connect_impl():
    conn = RstCloudConnector(
        instance_name="test_rstcloud",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.rstcloud.rstcloud.requests.Session") as mock_session:
        conn._connect_impl()
        mock_session.assert_called_once()
        assert conn._session is not None


def test_rstcloud_check_ip():
    conn = RstCloudConnector(
        instance_name="test_rstcloud",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.rstcloud.rstcloud.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ip": "8.8.8.8", "reputation": "clean"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_ip("8.8.8.8")
        assert result["reputation"] == "clean"


def test_rstcloud_check_domain():
    conn = RstCloudConnector(
        instance_name="test_rstcloud",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.rstcloud.rstcloud.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"domain": "example.com", "reputation": "clean"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_domain("example.com")
        assert result["reputation"] == "clean"


def test_rstcloud_check_hash():
    conn = RstCloudConnector(
        instance_name="test_rstcloud",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.rstcloud.rstcloud.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"sha256": "abc123", "reputation": "malicious"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_hash("abc123def456")
        assert result["reputation"] == "malicious"


def test_rstcloud_check_url():
    conn = RstCloudConnector(
        instance_name="test_rstcloud",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.rstcloud.rstcloud.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"url": "http://example.com", "reputation": "clean"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.check_url("http://example.com")
        assert result["reputation"] == "clean"


def test_rstcloud_disconnect():
    conn = RstCloudConnector(
        instance_name="test_rstcloud",
        api_key="TEST_KEY",
    )
    with patch("soar.connectors.rstcloud.rstcloud.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_rstcloud_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/rstcloud/__init__.py`:
```python
from soar.connectors.rstcloud.rstcloud import RstCloudConnector

__all__ = ["RstCloudConnector"]
```

`soar/connectors/rstcloud/rstcloud.py`:
```python
import requests

from soar.connectors.base import BaseConnector


class RstCloudConnector(BaseConnector):
    BASE_URL = "https://opentip.rstcloud.net"

    def __init__(
        self,
        instance_name: str,
        api_key: str,
        base_url: str = "",
        verify_ssl: bool = True,
    ):
        super().__init__(instance_name)
        self.api_key = api_key
        self.base_url = base_url or self.BASE_URL
        self.verify_ssl = verify_ssl
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.api_key}"
        self._session.headers["Accept"] = "application/json"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def check_ip(self, ip: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/ip/{ip}",
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def check_domain(self, domain: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/domain/{domain}",
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def check_hash(self, hash_value: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/file/{hash_value}",
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def check_url(self, url: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/api/v1/url",
            params={"url": url},
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()
```

`soar/connectors/rstcloud/rstcloud.example.yml`:
```yaml
instances:
  rstcloud_main:
    api_key: YOUR_RSTCLOUD_API_KEY
    verify_ssl: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_rstcloud_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/rstcloud/ tests/soar/test_rstcloud_connector.py
git commit -m "feat: add RstCloud connector for threat intelligence"
```

---

### Task 10: crt.sh Connector

**Covers:** Certificate transparency — search certificates by domain, find subdomains, check certificate issuance

**Files:**
- Create: `soar/connectors/crtsh/__init__.py`
- Create: `soar/connectors/crtsh/crtsh.py`
- Create: `soar/connectors/crtsh/crtsh.example.yml`
- Test: `tests/soar/test_crtsh_connector.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from soar.connectors.crtsh.crtsh import CrtshConnector


def test_crtsh_init():
    conn = CrtshConnector(instance_name="test_crtsh")
    assert conn.instance_name == "test_crtsh"
    assert conn.base_url == "https://crt.sh"
    assert conn.is_connected is False


def test_crtsh_connect_impl():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.requests.Session") as mock_session:
        conn._connect_impl()
        mock_session.assert_called_once()
        assert conn._session is not None


def test_crtsh_search_domain():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"id": 1, "common_name": "www.example.com", "issuer_ca_id": 123},
            {"id": 2, "common_name": "mail.example.com", "issuer_ca_id": 123},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.search_domain("example.com")
        assert len(result) == 2
        assert result[0]["common_name"] == "www.example.com"


def test_crtsh_search_domain_with_wildcard():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1, "common_name": "%.example.com"}]
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.search_domain("example.com", include_subdomains=True)
        assert len(result) == 1
        mock_session.get.assert_called_once()


def test_crtsh_search_identity():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1, "common_name": "example.com"}]
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.search_identity("example.com")
        assert len(result) == 1


def test_crtsh_get_certificate():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 12345, "common_name": "example.com"}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session
        conn._connect_impl()
        conn._connected = True

        result = conn.get_certificate("12345")
        assert result["id"] == 12345


def test_crtsh_disconnect():
    conn = CrtshConnector(instance_name="test_crtsh")
    with patch("soar.connectors.crtsh.crtsh.requests.Session"):
        conn._connect_impl()
        conn._connected = True
    conn.disconnect()
    assert conn.is_connected is False
    assert conn._session is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/soar/test_crtsh_connector.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write implementation**

`soar/connectors/crtsh/__init__.py`:
```python
from soar.connectors.crtsh.crtsh import CrtshConnector

__all__ = ["CrtshConnector"]
```

`soar/connectors/crtsh/crtsh.py`:
```python
import requests

from soar.connectors.base import BaseConnector


class CrtshConnector(BaseConnector):
    BASE_URL = "https://crt.sh"

    def __init__(self, instance_name: str, base_url: str = ""):
        super().__init__(instance_name)
        self.base_url = base_url or self.BASE_URL
        self._session: requests.Session | None = None

    def _connect_impl(self):
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"

    def disconnect(self):
        if self._session:
            self._session.close()
            self._session = None
            self._connected = False
            self._logger.info(f"Disconnected from {self.instance_name}")

    def search_domain(self, domain: str, include_subdomains: bool = False) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        query = f"%.{domain}" if include_subdomains else domain
        resp = self._session.get(
            f"{self.base_url}/q/",
            params={"q": query, "output": "json"},
        )
        resp.raise_for_status()
        return resp.json()

    def search_identity(self, identity: str) -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/q/",
            params={"identity": identity, "output": "json"},
        )
        resp.raise_for_status()
        return resp.json()

    def get_certificate(self, cert_id: str) -> dict:
        self._ensure_connected()
        assert self._session is not None
        resp = self._session.get(
            f"{self.base_url}/d/",
            params={"id": cert_id, "output": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data, list) and data else data
```

`soar/connectors/crtsh/crtsh.example.yml`:
```yaml
instances:
  crtsh_main: {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/soar/test_crtsh_connector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soar/connectors/crtsh/ tests/soar/test_crtsh_connector.py
git commit -m "feat: add crt.sh connector for certificate transparency"
```

---

### Task 11: Add new dependencies to requirements.txt

**Covers:** Adding pywinrm, impacket, shodan, pymisp to the project dependencies

**Files:**
- Modify: `soar/requirements.txt`

- [ ] **Step 1: Update requirements.txt**

Add these lines to `soar/requirements.txt`:
```
pywinrm>=0.5.0
impacket>=0.12.0
shodan>=1.31.0
pymisp>=2.4.180
```

- [ ] **Step 2: Verify no syntax errors**

Run: `python -c "import ast; open('soar/requirements.txt').read()"`
Expected: no error

- [ ] **Step 3: Commit**

```bash
git add soar/requirements.txt
git commit -m "chore: add dependencies for new connectors"
```

---

### Task 12: Run all connector tests

**Covers:** Verify all new connectors pass their tests

**Files:** None (verification only)

- [ ] **Step 1: Run all new connector tests**

Run: `python -m pytest tests/soar/test_winrm_connector.py tests/soar/test_smb_rpc_connector.py tests/soar/test_shodan_connector.py tests/soar/test_censys_connector.py tests/soar/test_fofa_connector.py tests/soar/test_urlhaus_connector.py tests/soar/test_kaspersky_opentip_connector.py tests/soar/test_misp_connector.py tests/soar/test_rstcloud_connector.py tests/soar/test_crtsh_connector.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run lint**

Run: `ruff check soar/connectors/ tests/soar/`
Expected: no errors

- [ ] **Step 3: Run type check**

Run: `mypy soar/connectors/winrm/ soar/connectors/smb_rpc/ soar/connectors/shodan/ soar/connectors/censys/ soar/connectors/fofa/ soar/connectors/urlhaus/ soar/connectors/kaspersky_opentip/ soar/connectors/misp/ soar/connectors/rstcloud/ soar/connectors/crtsh/ --ignore-missing-imports`
Expected: no errors
