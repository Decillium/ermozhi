import os
import sys
import json
import logging
import datetime
import argparse
from typing import Optional, Dict, Any, List

from src.data.storage.blob_repo import BlobStorageRepository, BlobPathBuilder

logger = logging.getLogger("EventReplayTool")


class EventReplayManager:
    """
    Operator tooling to inspect and safely replay failed/poison messages
    from work/dead-letter/ or historical events/ back into inbox/ with audit logging.
    """

    def __init__(self, repository: Optional[BlobStorageRepository] = None):
        self.repository = repository or BlobStorageRepository()

    def list_dead_letters(self) -> List[Dict[str, Any]]:
        """
        Lists all messages currently in the Dead-Letter Queue (work/dead-letter/).
        """
        blobs = self.repository.list_blobs(prefix="work/dead-letter/")
        results = []
        for blob_path in blobs:
            data = self.repository.load_json(blob_path)
            if data and isinstance(data, dict):
                results.append({
                    "blob_path": blob_path,
                    "message_id": data.get("message_id", os.path.basename(blob_path)[:-5]),
                    "dead_lettered_at": data.get("dead_lettered_at"),
                    "error_reason": data.get("error_reason"),
                    "payload": data
                })
        return results

    def replay_dead_letter(
        self,
        message_id: str,
        operator_id: str = "operator_manual",
        reason: str = "Manual investigation and bug fix deployed"
    ) -> Dict[str, Any]:
        """
        Replays a dead-lettered message back into inbox/ with audit metadata and attempt count reset.
        """
        dlq_path = BlobPathBuilder.work_dead_letter_path(message_id)
        dlq_data = self.repository.load_json(dlq_path)

        if not dlq_data:
            raise ValueError(f"No dead-letter message found for message_id '{message_id}' at '{dlq_path}'.")

        # Extract original inbox payload
        original_payload = dlq_data.get("original_payload") or dlq_data
        
        # Reset attempt and attach audit trail
        replayed_work_item = dict(original_payload)
        replayed_work_item["message_id"] = message_id
        replayed_work_item["attempt"] = 1
        replayed_work_item["replayed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        replayed_work_item["replayed_by"] = operator_id
        replayed_work_item["replay_reason"] = reason

        inbox_path = f"inbox/{message_id}.json"
        self.repository.save_json(inbox_path, replayed_work_item)
        self.repository.delete_blob(dlq_path)

        logger.info(f"Replayed message '{message_id}' from dead-letter to inbox (Operator: {operator_id}, Reason: {reason}).")
        return replayed_work_item

    def replay_from_event(
        self,
        event_path: str,
        operator_id: str = "operator_manual",
        reason: str = "Event log re-ingestion"
    ) -> Dict[str, Any]:
        """
        Re-enqueues an event from the immutable event log back into inbox/.
        """
        event_data = self.repository.load_json(event_path)
        if not event_data:
            raise ValueError(f"Event blob not found at '{event_path}'.")

        payload = event_data.get("payload", {})
        message_id = event_data.get("message_id") or payload.get("message_id") or f"msg_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}"

        work_item = {
            "message_id": message_id,
            "event_id": event_data.get("event_id"),
            "provider": payload.get("provider", "meta_whatsapp"),
            "channel": payload.get("channel", "whatsapp"),
            "status": "ACCEPTED",
            "enqueued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "input": payload.get("input", {}),
            "participant_ref": payload.get("participant_ref"),
            "locale_hint": payload.get("locale_hint", "ta-IN"),
            "attempt": 1,
            "replayed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "replayed_by": operator_id,
            "replay_reason": reason
        }

        inbox_path = f"inbox/{message_id}.json"
        self.repository.save_json(inbox_path, work_item)
        logger.info(f"Replayed historical event '{event_path}' to '{inbox_path}'.")
        return work_item


def main():
    parser = argparse.ArgumentParser(description="Ermozhi - Event Replay & DLQ Management CLI")
    parser.add_argument("--list-dlq", action="store_true", help="List all dead-lettered messages")
    parser.add_argument("--replay-dlq", type=str, help="Message ID to replay from DLQ")
    parser.add_argument("--replay-event", type=str, help="Blob path of historical event to replay")
    parser.add_argument("--operator", type=str, default="cli_operator", help="Operator username/identity")
    parser.add_argument("--reason", type=str, default="CLI manual replay", help="Reason for replaying message")

    args = parser.parse_args()
    manager = EventReplayManager()

    if args.list_dlq:
        dlq_items = manager.list_dead_letters()
        print(f"\n--- DEAD-LETTER QUEUE ({len(dlq_items)} items) ---")
        for item in dlq_items:
            print(f"Message ID : {item['message_id']}")
            print(f"Failed At  : {item['dead_lettered_at']}")
            print(f"Reason     : {item['error_reason']}")
            print("-" * 50)
    elif args.replay_dlq:
        res = manager.replay_dead_letter(args.replay_dlq, operator_id=args.operator, reason=args.reason)
        print(f"Successfully replayed {args.replay_dlq} into inbox/.")
    elif args.replay_event:
        res = manager.replay_from_event(args.replay_event, operator_id=args.operator, reason=args.reason)
        print(f"Successfully replayed event {args.replay_event} into inbox/ as message {res['message_id']}.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
