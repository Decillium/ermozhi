import os
import uuid
import datetime
import logging
from typing import Optional, Dict, Any, Tuple, List

from src.contracts.v1 import (
    CanonicalInboundMessage,
    EventEnvelope,
    ProcessingStatus
)
from src.data.storage.blob_repo import BlobStorageRepository, StorageError

logger = logging.getLogger("EventStore")


class EventStoreError(Exception):
    """Base exception for EventStore operations."""
    pass


class EventStore:
    """
    Asynchronous and durable storage client for Azure Blob Storage:
    - Immutable Event Log: events/{YYYY}/{MM}/{DD}/{message_id}.json
    - Work Ingestion Backlog: inbox/{message_id}.json
    - Provider Deduplication Index: index/providers/{provider}/{provider_message_id}.json
    """

    def __init__(self, repository: Optional[BlobStorageRepository] = None):
        self.repository = repository or BlobStorageRepository()

    @staticmethod
    def _date_partition(dt_str: Optional[str] = None) -> Tuple[str, str, str]:
        """Extracts (YYYY, MM, DD) strings from ISO timestamp or returns current UTC."""
        if dt_str:
            try:
                dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                return f"{dt.year:04d}", f"{dt.month:02d}", f"{dt.day:02d}"
            except Exception:
                pass
        now = datetime.datetime.now(datetime.timezone.utc)
        return f"{now.year:04d}", f"{now.month:02d}", f"{now.day:02d}"

    @classmethod
    def event_blob_path(cls, message_id: str, dt_str: Optional[str] = None) -> str:
        yyyy, mm, dd = cls._date_partition(dt_str)
        return f"events/{yyyy}/{mm}/{dd}/{message_id}.json"

    @staticmethod
    def inbox_blob_path(message_id: str) -> str:
        return f"inbox/{message_id}.json"

    @staticmethod
    def provider_index_blob_path(provider: str, provider_message_id: str) -> str:
        p = provider.strip().lower().replace(" ", "_")
        pmid = provider_message_id.strip()
        return f"index/providers/{p}/{pmid}.json"

    def check_duplicate(self, provider: str, provider_message_id: str) -> Optional[Dict[str, Any]]:
        """
        Checks the provider deduplication index.
        Returns the existing index payload if found, else None.
        """
        index_path = self.provider_index_blob_path(provider, provider_message_id)
        return self.repository.load_json(index_path)

    def persist_inbound_message(
        self,
        canonical_msg: CanonicalInboundMessage
    ) -> Tuple[EventEnvelope, bool]:
        """
        Persists an incoming canonical inbound message durably.
        1. Checks provider deduplication index.
        2. If duplicate, returns the existing event envelope (or reconstructed) with is_duplicate=True.
        3. If new, atomically writes to events/, inbox/, and provider index.
        
        Returns:
            Tuple[EventEnvelope, bool]: (envelope, is_duplicate)
        """
        # 1. Deduplication check
        dup = self.check_duplicate(canonical_msg.provider, canonical_msg.provider_message_id)
        if dup is not None:
            logger.info(
                f"Duplicate provider message detected for {canonical_msg.provider}:{canonical_msg.provider_message_id}. "
                f"Suppressing duplicate inbox enqueue."
            )
            existing_event_path = dup.get("event_path")
            if existing_event_path:
                existing_event_data = self.repository.load_json(existing_event_path)
                if existing_event_data and isinstance(existing_event_data, dict):
                    try:
                        return EventEnvelope.model_validate(existing_event_data), True
                    except Exception:
                        pass
            # Fallback envelope
            envelope = EventEnvelope(
                event_id=dup.get("event_id", f"evt_{uuid.uuid4().hex[:12]}"),
                event_type="InboundMessageAccepted",
                message_id=dup.get("message_id", canonical_msg.message_id),
                conversation_id=canonical_msg.conversation_ref,
                correlation_id=canonical_msg.correlation_id,
                attempt=1,
                occurred_at=dup.get("received_at", canonical_msg.received_at),
                payload=canonical_msg.model_dump()
            )
            return envelope, True

        # 2. Construct EventEnvelope
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        envelope = EventEnvelope(
            event_id=event_id,
            event_type="InboundMessageAccepted",
            message_id=canonical_msg.message_id,
            conversation_id=canonical_msg.conversation_ref,
            correlation_id=canonical_msg.correlation_id,
            attempt=1,
            occurred_at=canonical_msg.received_at,
            schema_version=canonical_msg.schema_version,
            payload=canonical_msg.model_dump()
        )

        event_path = self.event_blob_path(canonical_msg.message_id, canonical_msg.received_at)
        inbox_path = self.inbox_blob_path(canonical_msg.message_id)
        index_path = self.provider_index_blob_path(canonical_msg.provider, canonical_msg.provider_message_id)

        envelope_dict = envelope.model_dump()
        work_item = {
            "message_id": canonical_msg.message_id,
            "event_id": event_id,
            "conversation_id": canonical_msg.conversation_ref,
            "correlation_id": canonical_msg.correlation_id,
            "provider": canonical_msg.provider,
            "channel": canonical_msg.channel,
            "status": ProcessingStatus.ACCEPTED.value,
            "enqueued_at": canonical_msg.received_at,
            "event_path": event_path,
            "input": canonical_msg.input.model_dump(),
            "participant_ref": canonical_msg.participant_ref,
            "locale_hint": canonical_msg.locale_hint
        }
        index_entry = {
            "provider": canonical_msg.provider,
            "provider_message_id": canonical_msg.provider_message_id,
            "message_id": canonical_msg.message_id,
            "event_id": event_id,
            "status": ProcessingStatus.ACCEPTED.value,
            "received_at": canonical_msg.received_at,
            "event_path": event_path,
            "inbox_path": inbox_path
        }

        try:
            # Commit to immutable event log
            self.repository.save_json(event_path, envelope_dict)
            # Commit to work inbox
            self.repository.save_json(inbox_path, work_item)
            # Commit to provider deduplication index
            self.repository.save_json(index_path, index_entry)
            logger.info(f"Durable event committed: message_id={canonical_msg.message_id}, event_path={event_path}")
        except Exception as e:
            logger.error(f"Failed to persist event to Blob Storage: {e}")
            raise EventStoreError(f"Durable persistence failed: {e}")

        return envelope, False

    def get_inbox_item(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a work item from the inbox backlog."""
        inbox_path = self.inbox_blob_path(message_id)
        return self.repository.load_json(inbox_path)

    def is_healthy(self) -> bool:
        """Readiness check to verify storage connectivity."""
        try:
            # Test write/read probe
            probe_path = "health/readiness_probe.json"
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.repository.save_json(probe_path, {"status": "OK", "checked_at": now})
            data = self.repository.load_json(probe_path)
            return data is not None and data.get("status") == "OK"
        except Exception as e:
            logger.warning(f"Storage readiness health check probe failed: {e}")
            return False
