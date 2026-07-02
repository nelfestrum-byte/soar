from smbprotocol.connection import Connection
from smbprotocol.file_info import FileDirectoryInformation
from smbprotocol.open import (
    CreateDisposition,
    DirectoryAccessMask,
    FilePipePrinterAccessMask,
    ImpersonationLevel,
    Open,
    ShareAccess,
)
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect

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
    ):
        super().__init__(instance_name)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.domain = domain
        self._connection: Connection | None = None
        self._session: Session | None = None
        self._tree: TreeConnect | None = None

    def _connect_impl(self):
        self._connection = Connection(uuid_generate=True, server_name=self.host, port=self.port)
        self._connection.connect()
        self._session = Session(self._connection, username=self.username, password=self.password, domain=self.domain)
        self._session.connect()

    def disconnect(self):
        if self._tree:
            try:
                self._tree.disconnect()
            except Exception:
                pass
            self._tree = None
        if self._session:
            try:
                self._session.disconnect()
            except Exception:
                pass
            self._session = None
        if self._connection:
            try:
                self._connection.disconnect()
            except Exception:
                pass
            self._connection = None
        self._connected = False
        self._logger.info(f"Disconnected from {self.instance_name}")

    def _get_tree(self, share: str) -> TreeConnect:
        if self._tree is None or self._tree.share_name != share:
            if self._tree:
                try:
                    self._tree.disconnect()
                except Exception:
                    pass
            self._tree = TreeConnect(self._session, f"\\\\{self.host}\\{share}")
            self._tree.connect()
        return self._tree

    def list_files(self, share: str, path: str = "") -> list[dict]:
        self._ensure_connected()
        assert self._session is not None
        tree = self._get_tree(share)
        file_path = f"{path}\\*" if path else "*"
        file = Open(tree, file_path, create_options=0x20, create_disp=CreateDisposition.FILE_OPEN)
        file.create(impersonation=ImpersonationLevel.Impersonation, desired_access=DirectoryAccessMask.FILE_LIST_DIRECTORY, share_access=ShareAccess.FILE_SHARE_READ, create_disposition=CreateDisposition.FILE_OPEN, create_options=0x20)
        try:
            entries, _ = file.query_directory(FileDirectoryInformation, 0)
            result = []
            for entry in entries:
                name = entry["file_name"]
                if name in (".", ".."):
                    continue
                result.append({
                    "filename": name,
                    "file_size": entry["end_of_file"],
                    "is_directory": bool(entry["file_attributes"] & 0x10),
                    "create_time": str(entry["creation_time"]),
                    "last_access_time": str(entry["last_access"]),
                    "last_write_time": str(entry["last_write"]),
                })
            return result
        finally:
            file.close()

    def upload_file(self, share: str, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._session is not None
        tree = self._get_tree(share)
        with open(local_path, "rb") as f:
            data = f.read()
        file = Open(tree, remote_path)
        file.create(impersonation=ImpersonationLevel.Impersonation, desired_access=FilePipePrinterAccessMask.FILE_WRITE_DATA, share_access=0, create_disposition=CreateDisposition.FILE_OVERWRITE_IF)
        try:
            file.write(data, 0)
        finally:
            file.close()
        return True

    def download_file(self, share: str, remote_path: str, local_path: str) -> bool:
        self._ensure_connected()
        assert self._session is not None
        tree = self._get_tree(share)
        file = Open(tree, remote_path)
        file.create(impersonation=ImpersonationLevel.Impersonation, desired_access=FilePipePrinterAccessMask.FILE_READ_DATA, share_access=ShareAccess.FILE_SHARE_READ, create_disposition=CreateDisposition.FILE_OPEN)
        try:
            data = file.read(0, file.query_file(0)["end_of_file"])
            with open(local_path, "wb") as f:
                f.write(data)
        finally:
            file.close()
        return True

    def delete_file(self, share: str, path: str) -> bool:
        self._ensure_connected()
        assert self._session is not None
        tree = self._get_tree(share)
        file = Open(tree, path)
        file.create(impersonation=ImpersonationLevel.Impersonation, desired_access=FilePipePrinterAccessMask.DELETE, share_access=0, create_disposition=CreateDisposition.FILE_OPEN)
        try:
            file.close(delete_on_close=True)
        except Exception:
            file.close()
        return True

    def check_file_exists(self, share: str, path: str) -> bool:
        self._ensure_connected()
        assert self._session is not None
        tree = self._get_tree(share)
        try:
            file = Open(tree, path)
            file.create(impersonation=ImpersonationLevel.Impersonation, desired_access=FilePipePrinterAccessMask.FILE_READ_ATTRIBUTES, share_access=ShareAccess.FILE_SHARE_READ, create_disposition=CreateDisposition.FILE_OPEN)
            file.close()
            return True
        except Exception:
            return False
