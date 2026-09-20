import hmac
import hashlib
import base64
from typing import Dict, Any, Optional


class SecurityError(Exception):
    """Base exception for gateway security errors."""
    pass


class SignatureVerificationError(SecurityError):
    """Raised when webhook signature verification fails."""
    pass


class SecurityConfigurationError(SecurityError):
    """Raised when required security credentials (keys, tokens) are missing."""
    pass


def verify_meta_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    app_secret: str,
    raise_on_failure: bool = True
) -> bool:
    """
    Verifies Meta WhatsApp Cloud API webhook signature (HMAC-SHA256).
    Carried in the X-Hub-Signature-256 header.
    Format: 'sha256=<hex_digest>'
    
    Fail-closed: returns False or raises SignatureVerificationError on any mismatch.
    """
    if not app_secret or not app_secret.strip():
        raise SecurityConfigurationError("Meta app secret must be configured; fail-closed.")

    if not signature_header or not signature_header.strip():
        if raise_on_failure:
            raise SignatureVerificationError("Missing X-Hub-Signature-256 header.")
        return False

    sig_header = signature_header.strip()
    if not sig_header.startswith("sha256="):
        if raise_on_failure:
            raise SignatureVerificationError("Invalid signature format. Expected 'sha256=<hash>'.")
        return False

    actual_sig = sig_header[len("sha256="):].strip()

    expected_sig = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_sig, actual_sig)

    if not is_valid and raise_on_failure:
        raise SignatureVerificationError("Meta HMAC-SHA256 signature verification failed.")

    return is_valid
