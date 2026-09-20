"""
Security filters and validation utilities for Ermozhi Gateway.
Enforces HMAC signature verification, SSRF prevention, and media payload sanitization.
"""

from src.gateway.security.signature import (
    SecurityError,
    SignatureVerificationError,
    SecurityConfigurationError,
    verify_meta_signature,
)

from src.gateway.security.sanitizer import (
    SSRFProtectionError,
    MediaValidationError,
    DEFAULT_APPROVED_CDN_DOMAINS,
    ALLOWED_AUDIO_MIME_TYPES,
    MAX_MEDIA_SIZE_BYTES,
    validate_media_url,
    validate_media_payload,
)

__all__ = [
    # Exceptions
    "SecurityError",
    "SignatureVerificationError",
    "SecurityConfigurationError",
    "SSRFProtectionError",
    "MediaValidationError",
    # Signature verifiers
    "verify_meta_signature",
    # Sanitizers
    "validate_media_url",
    "validate_media_payload",
    # Constants
    "DEFAULT_APPROVED_CDN_DOMAINS",
    "ALLOWED_AUDIO_MIME_TYPES",
    "MAX_MEDIA_SIZE_BYTES",
]
