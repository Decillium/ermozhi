import os
import json
import logging
from typing import Optional, Dict, Any, List, Union
from datetime import datetime, date, timezone

logger = logging.getLogger("MarketStorageRepository")


class StorageError(Exception):
    """Base exception for storage repository errors."""
    pass


class BlobPathBuilder:
    """
    Standardizes Azure Blob Storage paths for the Data Layer according to architecture:
    - Raw: market/raw/{source}/{YYYY}/{MM}/{DD}/{batch_id}.json
    - Curated: market/curated/{commodity}/{state}/{district}/{YYYY}/{MM}.json
    - Snapshots: market/snapshots/{commodity}/{variety}/{district}/latest.json
    - Versioned Snapshots: market/snapshots/{commodity}/{variety}/{district}/snapshot_{timestamp}_{batch_id}.json
    - Quarantine: market/quarantine/{batch_id}.json
    """

    @staticmethod
    def raw_path(source: str, dt: Union[datetime, date, str], batch_id: str) -> str:
        if isinstance(dt, str):
            # parse YYYY-MM-DD
            parts = dt.split("T")[0].split("-")
            yyyy, mm, dd = parts[0], parts[1], parts[2]
        else:
            yyyy = f"{dt.year:04d}"
            mm = f"{dt.month:02d}"
            dd = f"{dt.day:02d}"
        source_clean = source.strip().lower().replace(".", "_")
        return f"market/raw/{source_clean}/{yyyy}/{mm}/{dd}/{batch_id}.json"

    @staticmethod
    def curated_path(commodity: str, state: str, district: str, year: int, month: int) -> str:
        c = commodity.strip().lower()
        s = state.strip().lower().replace(" ", "_")
        d = district.strip().lower().replace(" ", "_")
        return f"market/curated/{c}/{s}/{d}/{year:04d}/{month:02d}.json"

    @staticmethod
    def snapshot_latest_path(commodity: str, variety: str, district: str) -> str:
        c = commodity.strip().lower()
        v = variety.strip().lower()
        d = district.strip().lower().replace(" ", "_")
        return f"market/snapshots/{c}/{v}/{d}/latest.json"

    @staticmethod
    def snapshot_versioned_path(commodity: str, variety: str, district: str, timestamp_str: str, batch_id: str) -> str:
        c = commodity.strip().lower()
        v = variety.strip().lower()
        d = district.strip().lower().replace(" ", "_")
        return f"market/snapshots/{c}/{v}/{d}/snapshot_{timestamp_str}_{batch_id}.json"

    @staticmethod
    def quarantine_path(batch_id: str) -> str:
        return f"market/quarantine/{batch_id}.json"

    @staticmethod
    def media_inbound_path(dt: Union[datetime, date, str], message_id: str, extension: str = "ogg") -> str:
        if isinstance(dt, str):
            parts = dt.split("T")[0].split("-")
            yyyy, mm, dd = parts[0], parts[1], parts[2]
        else:
            yyyy = f"{dt.year:04d}"
            mm = f"{dt.month:02d}"
            dd = f"{dt.day:02d}"
        ext = extension.lstrip(".")
        return f"media/inbound/{yyyy}/{mm}/{dd}/{message_id}.{ext}"

    @staticmethod
    def media_outbound_path(dt: Union[datetime, date, str], response_id: str, extension: str = "mp3") -> str:
        if isinstance(dt, str):
            parts = dt.split("T")[0].split("-")
            yyyy, mm, dd = parts[0], parts[1], parts[2]
        else:
            yyyy = f"{dt.year:04d}"
            mm = f"{dt.month:02d}"
            dd = f"{dt.day:02d}"
        ext = extension.lstrip(".")
        return f"media/outbound/{yyyy}/{mm}/{dd}/{response_id}.{ext}"

    @staticmethod
    def work_active_path(message_id: str) -> str:
        return f"work/active/{message_id}.json"

    @staticmethod
    def work_dead_letter_path(message_id: str) -> str:
        return f"work/dead-letter/{message_id}.json"

    @staticmethod
    def event_status_path(dt: Union[datetime, date, str], message_id: str) -> str:
        if isinstance(dt, str):
            parts = dt.split("T")[0].split("-")
            yyyy, mm, dd = parts[0], parts[1], parts[2]
        else:
            yyyy = f"{dt.year:04d}"
            mm = f"{dt.month:02d}"
            dd = f"{dt.day:02d}"
        return f"events/{yyyy}/{mm}/{dd}/{message_id}_status.json"


class BlobStorageRepository:
    """
    Unified Storage Repository for market data.
    Supports local filesystem / virtual in-memory store for development/testing,
    and Azure Blob Storage SDK in cloud environments.
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        use_memory_store: bool = False,
        connection_string: Optional[str] = None,
        container_name: str = "market"
    ):
        self.use_memory_store = use_memory_store
        self._memory_store: Dict[str, str] = {}
        self.base_dir = base_dir or os.getenv("STORAGE_BASE_DIR", os.path.join(os.getcwd(), ".storage_data"))
        self.connection_string = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self.container_name = container_name
        self.blob_service_client = None

        if not self.use_memory_store and self.connection_string:
            try:
                from azure.storage.blob import BlobServiceClient
                self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
                logger.info("Connected to Azure Blob Storage.")
            except ImportError:
                logger.warning("azure-storage-blob package not installed; falling back to filesystem storage.")
            except Exception as e:
                logger.warning(f"Failed to connect to Azure Blob Storage ({e}); using filesystem storage.")

    def save_json(self, blob_path: str, data: Union[Dict[str, Any], List[Any]], indent: int = 2) -> str:
        """Saves a Python dict or list as a JSON blob."""
        json_str = json.dumps(data, indent=indent, ensure_ascii=False)

        if self.use_memory_store:
            self._memory_store[blob_path] = json_str
            return blob_path

        if self.blob_service_client:
            try:
                container_client = self.blob_service_client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(blob_path)
                blob_client.upload_blob(json_str.encode("utf-8"), overwrite=True)
                return blob_path
            except Exception as e:
                logger.error(f"Error uploading blob '{blob_path}' to Azure: {e}")
                raise StorageError(f"Azure Blob Storage upload failed: {e}")

        # Local filesystem fallback
        full_path = os.path.join(self.base_dir, blob_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(json_str)

        return blob_path

    def load_json(self, blob_path: str) -> Optional[Union[Dict[str, Any], List[Any]]]:
        """Loads and parses a JSON blob from storage."""
        if self.use_memory_store:
            if blob_path in self._memory_store:
                return json.loads(self._memory_store[blob_path])
            return None

        if self.blob_service_client:
            try:
                container_client = self.blob_service_client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(blob_path)
                if blob_client.exists():
                    data = blob_client.download_blob().readall()
                    return json.loads(data.decode("utf-8"))
                return None
            except Exception as e:
                logger.error(f"Error downloading blob '{blob_path}' from Azure: {e}")
                raise StorageError(f"Azure Blob Storage download failed: {e}")

        full_path = os.path.join(self.base_dir, blob_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                return json.load(f)

        return None

    def exists(self, blob_path: str) -> bool:
        """Checks if a blob exists."""
        if self.use_memory_store:
            return blob_path in self._memory_store

        if self.blob_service_client:
            try:
                container_client = self.blob_service_client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(blob_path)
                return blob_client.exists()
            except Exception:
                return False

        full_path = os.path.join(self.base_dir, blob_path)
        return os.path.exists(full_path)

    def list_blobs(self, prefix: str = "") -> List[str]:
        """Lists blob paths matching a prefix."""
        if self.use_memory_store:
            return [k for k in self._memory_store.keys() if k.startswith(prefix)]

        if self.blob_service_client:
            try:
                container_client = self.blob_service_client.get_container_client(self.container_name)
                return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]
            except Exception as e:
                logger.error(f"Error listing blobs with prefix '{prefix}': {e}")
                return []

        matched = []
        search_dir = os.path.join(self.base_dir, prefix)
        if os.path.exists(search_dir):
            for root, _, files in os.walk(search_dir):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, self.base_dir).replace("\\", "/")
                    matched.append(rel)
        return matched

    def save_bytes(self, blob_path: str, data: bytes, content_type: Optional[str] = None) -> str:
        """Saves raw binary bytes (e.g. audio files) to storage."""
        if self.use_memory_store:
            # Store base64 or raw bytes in memory store
            import base64
            self._memory_store[blob_path] = base64.b64encode(data).decode("utf-8")
            return blob_path

        if self.blob_service_client:
            try:
                from azure.storage.blob import ContentSettings
                container_client = self.blob_service_client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(blob_path)
                cs = ContentSettings(content_type=content_type) if content_type else None
                blob_client.upload_blob(data, overwrite=True, content_settings=cs)
                return blob_path
            except Exception as e:
                logger.error(f"Error uploading binary blob '{blob_path}' to Azure: {e}")
                raise StorageError(f"Azure Blob Storage upload failed: {e}")

        full_path = os.path.join(self.base_dir, blob_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)
        return blob_path

    def load_bytes(self, blob_path: str) -> Optional[bytes]:
        """Loads raw binary bytes from storage."""
        if self.use_memory_store:
            if blob_path in self._memory_store:
                import base64
                return base64.b64decode(self._memory_store[blob_path].encode("utf-8"))
            return None

        if self.blob_service_client:
            try:
                container_client = self.blob_service_client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(blob_path)
                if blob_client.exists():
                    return blob_client.download_blob().readall()
                return None
            except Exception as e:
                logger.error(f"Error downloading binary blob '{blob_path}' from Azure: {e}")
                raise StorageError(f"Azure Blob Storage download failed: {e}")

        full_path = os.path.join(self.base_dir, blob_path)
        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                return f.read()
        return None

    def delete_blob(self, blob_path: str) -> bool:
        """Deletes a blob from storage."""
        if self.use_memory_store:
            if blob_path in self._memory_store:
                del self._memory_store[blob_path]
                return True
            return False

        if self.blob_service_client:
            try:
                container_client = self.blob_service_client.get_container_client(self.container_name)
                blob_client = container_client.get_blob_client(blob_path)
                if blob_client.exists():
                    blob_client.delete_blob()
                    return True
                return False
            except Exception as e:
                logger.error(f"Error deleting blob '{blob_path}' from Azure: {e}")
                return False

        full_path = os.path.join(self.base_dir, blob_path)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
                return True
            except OSError:
                return False
        return False

    def generate_sas_url(self, blob_path: str, ttl_hours: int = 1) -> str:
        """Generates a secure SAS URL or pseudo-URI for the given blob."""
        if self.blob_service_client:
            try:
                from azure.storage.blob import generate_blob_sas, BlobSasPermissions
                from datetime import timedelta
                expiry = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
                sas_token = generate_blob_sas(
                    account_name=self.blob_service_client.account_name,
                    container_name=self.container_name,
                    blob_name=blob_path,
                    account_key=self.blob_service_client.credential.account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=expiry
                )
                return f"https://{self.blob_service_client.account_name}.blob.core.windows.net/{self.container_name}/{blob_path}?{sas_token}"
            except Exception as e:
                logger.warning(f"Could not generate live Azure SAS URL ({e}); returning signed URI format.")

        return f"https://storage.ermozhi.azure.com/{self.container_name}/{blob_path}?token=mock_sas_{ttl_hours}h"

    def clear(self) -> None:
        """Clears memory store (used in test teardowns)."""
        if self.use_memory_store:
            self._memory_store.clear()

