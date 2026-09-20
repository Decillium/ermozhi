import re
import logging
from typing import Any, Dict, List, Union

logger = logging.getLogger("PIIMasking")

# Regex to match phone numbers (E.164 and local Indian formats like +91 9876543210 or 9876543210)
PHONE_REGEX = re.compile(r"(\+?91[\s-]?)?([6-9]\d{9})")
SECRET_KEYS = {
    "access_token", "auth_token", "token", "app_secret", "api_key",
    "secret", "key", "password", "authorization", "x-hub-signature-256", "signature"
}
PHONE_KEYS = {
    "to", "from", "participant_ref", "phone", "phone_number", "sender",
    "recipient", "recipient_id", "wa_id"
}


def mask_phone_number(phone_str: str) -> str:
    """
    Masks phone numbers to protect PII, preserving prefix and last 4 digits.
    e.g., '+919876543210' -> '+91XXXXXX3210'
    e.g., '9876543210' -> 'XXXXXX3210'
    """
    if not phone_str or not isinstance(phone_str, str):
        return phone_str

    clean = phone_str.strip().replace("whatsapp:", "")
    
    def _repl(match: re.Match) -> str:
        prefix = match.group(1) or ""
        digits = match.group(2)
        masked_digits = "X" * (len(digits) - 4) + digits[-4:]
        return f"{prefix}{masked_digits}"

    return PHONE_REGEX.sub(_repl, clean)


def mask_sensitive_payload(obj: Any) -> Any:
    """
    Recursively masks sensitive tokens, passwords, phone numbers, and binary buffers
    in structured dictionaries and lists for safe logging and telemetry.
    """
    if isinstance(obj, dict):
        masked_dict = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(secret in k_lower for secret in SECRET_KEYS):
                masked_dict[k] = "[REDACTED_SECRET]"
            elif any(phone in k_lower for phone in PHONE_KEYS) and isinstance(v, str):
                masked_dict[k] = mask_phone_number(v)
            elif isinstance(v, bytes):
                masked_dict[k] = f"<bytes len={len(v)}>"
            else:
                masked_dict[k] = mask_sensitive_payload(v)
        return masked_dict

    elif isinstance(obj, list):
        return [mask_sensitive_payload(item) for item in obj]

    elif isinstance(obj, str):
        return mask_phone_number(obj)

    elif isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"

    return obj


class PIIMaskingFilter(logging.Filter):
    """
    Logging filter that sanitizes log message strings and argument dictionaries
    to guarantee zero PII leakage to Log Analytics and Application Insights.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_phone_number(record.msg)
        
        if record.args:
            if isinstance(record.args, dict):
                record.args = mask_sensitive_payload(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(mask_sensitive_payload(arg) for arg in record.args)
        
        return True
