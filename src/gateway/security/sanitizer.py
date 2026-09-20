import ipaddress
import socket
from urllib.parse import urlparse
from typing import List, Optional, Set

from src.gateway.security.signature import SecurityError


class SSRFProtectionError(SecurityError):
    """Raised when a media URL fails SSRF protection checks."""
    pass


class MediaValidationError(SecurityError):
    """Raised when media payload size or MIME type violates policy."""
    pass


# Strict allowlist of approved provider CDN domains
DEFAULT_APPROVED_CDN_DOMAINS: List[str] = [
    "lookaside.fbsbx.com",
    "fbcdn.net",
    "whatsapp.net",
]

# Strict allowlist of approved audio MIME types
ALLOWED_AUDIO_MIME_TYPES: Set[str] = {
    "audio/ogg",
    "audio/amr",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/aac",
    "audio/x-wav",
}

# 16 MB maximum media payload limit
MAX_MEDIA_SIZE_BYTES: int = 16 * 1024 * 1024  # 16,777,216 bytes


def is_ip_address(host: str) -> bool:
    """Checks if a host string is an IPv4 or IPv6 address literal."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_private_or_restricted_ip(ip_str: str) -> bool:
    """Checks if an IP string is private, loopback, link-local, or reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return True


def is_allowed_domain(hostname: str, approved_domains: List[str]) -> bool:
    """
    Checks if hostname matches or is a subdomain of any approved domain.
    E.g., 'scontent.xx.fbcdn.net' matches 'fbcdn.net'.
    """
    clean_host = hostname.lower().strip()
    for approved in approved_domains:
        approved = approved.lower().strip()
        if clean_host == approved or clean_host.endswith(f".{approved}"):
            return True
    return False


def validate_media_url(
    url: str,
    approved_domains: Optional[List[str]] = None,
    verify_dns: bool = True
) -> str:
    """
    Validates a media download URL against strict SSRF protection rules:
    1. Scheme must be HTTPS.
    2. IP address literals (IPv4 / IPv6) are strictly forbidden.
    3. Hostname must belong to an approved provider CDN domain.
    4. DNS resolution check: Hostname must not resolve to private/loopback/link-local IP addresses.
    
    Returns the validated URL if safe, or raises SSRFProtectionError.
    """
    if not url or not isinstance(url, str):
        raise SSRFProtectionError("Media URL must be a non-empty string.")

    parsed = urlparse(url.strip())

    # 1. Scheme check: only HTTPS allowed
    if parsed.scheme.lower() != "https":
        raise SSRFProtectionError(f"Insecure media scheme '{parsed.scheme}'. Only HTTPS is permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFProtectionError("Media URL is missing a valid hostname.")

    hostname_clean = hostname.strip().lower()

    # 2. IP literal check: Direct IP URLs are strictly rejected
    if is_ip_address(hostname_clean):
        raise SSRFProtectionError(f"Direct IP address literals are prohibited in media URLs: '{hostname_clean}'.")

    # Reject localhost / local domains explicitly
    if hostname_clean in {"localhost", "local", "internal"} or hostname_clean.endswith(".local") or hostname_clean.endswith(".internal"):
        raise SSRFProtectionError(f"Local and internal hostnames are prohibited: '{hostname_clean}'.")

    # 3. Domain allowlist check
    domain_list = approved_domains or DEFAULT_APPROVED_CDN_DOMAINS
    if not is_allowed_domain(hostname_clean, domain_list):
        raise SSRFProtectionError(
            f"Hostname '{hostname_clean}' is not in the approved provider CDN allowlist: {domain_list}"
        )

    # 4. DNS Anti-Rebinding Check: Ensure domain does not resolve to a private or loopback IP
    if verify_dns:
        try:
            addr_info = socket.getaddrinfo(hostname_clean, 443, proto=socket.IPPROTO_TCP)
            for entry in addr_info:
                sockaddr = entry[4]
                resolved_ip = sockaddr[0]
                if is_private_or_restricted_ip(resolved_ip):
                    raise SSRFProtectionError(
                        f"Hostname '{hostname_clean}' resolved to restricted/private IP: '{resolved_ip}'."
                    )
        except socket.gaierror as e:
            # If DNS resolution fails, reject the URL
            raise SSRFProtectionError(f"Failed to resolve hostname '{hostname_clean}': {e}")

    return url.strip()


def validate_media_payload(
    content_type: str,
    content_length: Optional[int] = None,
    allowed_types: Optional[Set[str]] = None,
    max_size_bytes: int = MAX_MEDIA_SIZE_BYTES
) -> None:
    """
    Validates media MIME type and payload size.
    
    Raises MediaValidationError if:
    - MIME type is not an approved audio format.
    - Content length exceeds the max size limit (16 MB).
    """
    if not content_type:
        raise MediaValidationError("Missing Content-Type header for media payload.")

    # Strip parameters (e.g. 'audio/ogg; codecs=opus' -> 'audio/ogg')
    base_type = content_type.split(";")[0].strip().lower()
    types_allowed = allowed_types or ALLOWED_AUDIO_MIME_TYPES

    if base_type not in types_allowed:
        raise MediaValidationError(
            f"Unauthorized media MIME type '{base_type}'. Allowed types: {sorted(types_allowed)}"
        )

    if content_length is not None:
        if content_length < 0:
            raise MediaValidationError(f"Invalid negative Content-Length: {content_length}")
        if content_length > max_size_bytes:
            raise MediaValidationError(
                f"Media payload exceeds maximum size limit of {max_size_bytes} bytes (got {content_length} bytes)."
            )
