import hmac
import hashlib
import pytest
from unittest.mock import patch
import socket

from src.gateway.security import (
    verify_meta_signature,
    validate_media_url,
    validate_media_payload,
    SignatureVerificationError,
    SecurityConfigurationError,
    SSRFProtectionError,
    MediaValidationError,
    MAX_MEDIA_SIZE_BYTES,
)


class TestMetaSignatureVerification:
    """Tests HMAC-SHA256 signature verification for Meta WhatsApp Cloud API."""

    APP_SECRET = "test_meta_app_secret_999"
    SAMPLE_BODY = b'{"object":"whatsapp_business_account","entry":[{"id":"123"}]}'

    def _generate_valid_header(self, body: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_meta_signature(self):
        valid_header = self._generate_valid_header(self.SAMPLE_BODY, self.APP_SECRET)
        assert verify_meta_signature(self.SAMPLE_BODY, valid_header, self.APP_SECRET) is True

    def test_tampered_payload_fails(self):
        valid_header = self._generate_valid_header(self.SAMPLE_BODY, self.APP_SECRET)
        tampered_body = b'{"object":"whatsapp_business_account","entry":[{"id":"456"}]}'
        with pytest.raises(SignatureVerificationError, match="signature verification failed"):
            verify_meta_signature(tampered_body, valid_header, self.APP_SECRET)

    def test_invalid_signature_header_fails(self):
        with pytest.raises(SignatureVerificationError, match="signature verification failed"):
            verify_meta_signature(
                self.SAMPLE_BODY,
                "sha256=0000000000000000000000000000000000000000000000000000000000000000",
                self.APP_SECRET
            )

    def test_missing_signature_header_fails(self):
        with pytest.raises(SignatureVerificationError, match="Missing X-Hub-Signature-256"):
            verify_meta_signature(self.SAMPLE_BODY, None, self.APP_SECRET)

        with pytest.raises(SignatureVerificationError, match="Missing X-Hub-Signature-256"):
            verify_meta_signature(self.SAMPLE_BODY, "", self.APP_SECRET)

    def test_malformed_signature_format_fails(self):
        with pytest.raises(SignatureVerificationError, match="Invalid signature format"):
            verify_meta_signature(self.SAMPLE_BODY, "invalid_no_sha256_prefix", self.APP_SECRET)

    def test_missing_app_secret_raises_config_error(self):
        with pytest.raises(SecurityConfigurationError, match="app secret must be configured"):
            verify_meta_signature(self.SAMPLE_BODY, "sha256=abc", "")


class TestSSRFProtectionAndURLSanitization:
    """Tests SSRF defense, IP filtering, scheme verification, and domain allowlists."""

    def test_reject_insecure_http_scheme(self):
        with pytest.raises(SSRFProtectionError, match="Only HTTPS is permitted"):
            validate_media_url("http://lookaside.fbsbx.com/media/audio.ogg", verify_dns=False)

    def test_reject_direct_ip_literals(self):
        # IPv4 Loopback
        with pytest.raises(SSRFProtectionError, match="Direct IP address literals are prohibited"):
            validate_media_url("https://127.0.0.1/audio.ogg", verify_dns=False)

        # RFC 1918 Private IPs
        with pytest.raises(SSRFProtectionError, match="Direct IP address literals are prohibited"):
            validate_media_url("https://192.168.1.1/audio.ogg", verify_dns=False)
        with pytest.raises(SSRFProtectionError, match="Direct IP address literals are prohibited"):
            validate_media_url("https://10.0.0.5/audio.ogg", verify_dns=False)

        # Cloud Metadata IP (AWS/Azure/GCP 169.254.169.254)
        with pytest.raises(SSRFProtectionError, match="Direct IP address literals are prohibited"):
            validate_media_url("https://169.254.169.254/latest/meta-data", verify_dns=False)

    def test_reject_local_hostnames(self):
        with pytest.raises(SSRFProtectionError, match="Local and internal hostnames are prohibited"):
            validate_media_url("https://localhost/audio.ogg", verify_dns=False)

        with pytest.raises(SSRFProtectionError, match="Local and internal hostnames are prohibited"):
            validate_media_url("https://server.local/audio.ogg", verify_dns=False)

    def test_reject_unapproved_domains(self):
        with pytest.raises(SSRFProtectionError, match="not in the approved provider CDN allowlist"):
            validate_media_url("https://malicious-site.com/audio.ogg", verify_dns=False)

        with pytest.raises(SSRFProtectionError, match="not in the approved provider CDN allowlist"):
            validate_media_url("https://attacker.lookaside.fbsbx.com.evil.com/audio.ogg", verify_dns=False)

    def test_accept_approved_cdn_domains(self):
        # Meta / Facebook CDN
        u1 = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=123"
        assert validate_media_url(u1, verify_dns=False) == u1

        u2 = "https://scontent.xx.fbcdn.net/v/t39.123/audio.ogg"
        assert validate_media_url(u2, verify_dns=False) == u2

        u3 = "https://mmg.whatsapp.net/v/t62.7118-24/audio.ogg"
        assert validate_media_url(u3, verify_dns=False) == u3

    def test_dns_rebinding_protection(self):
        """Simulate a DNS lookup resolving an approved domain to a private IP (e.g. 10.0.0.1)."""
        fake_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('10.0.0.1', 443))
        ]
        with patch("socket.getaddrinfo", return_value=fake_addr_info):
            with pytest.raises(SSRFProtectionError, match="resolved to restricted/private IP"):
                validate_media_url("https://lookaside.fbsbx.com/media/audio.ogg", verify_dns=True)


class TestMediaPayloadValidation:
    """Tests media MIME type allowlisting and payload size constraints."""

    def test_approved_audio_mime_types(self):
        for mime in ["audio/ogg", "audio/amr", "audio/mp4", "audio/mpeg", "audio/wav", "audio/ogg; codecs=opus"]:
            validate_media_payload(content_type=mime, content_length=1024)

    def test_unapproved_mime_types_rejected(self):
        for bad_mime in ["application/x-msdownload", "application/octet-stream", "text/html", "image/jpeg"]:
            with pytest.raises(MediaValidationError, match="Unauthorized media MIME type"):
                validate_media_payload(content_type=bad_mime, content_length=1024)

    def test_missing_mime_type_rejected(self):
        with pytest.raises(MediaValidationError, match="Missing Content-Type"):
            validate_media_payload(content_type="")

    def test_payload_size_boundary(self):
        # Exactly 16 MB is allowed
        validate_media_payload(content_type="audio/ogg", content_length=MAX_MEDIA_SIZE_BYTES)

        # 16 MB + 1 byte is rejected
        with pytest.raises(MediaValidationError, match="exceeds maximum size limit"):
            validate_media_payload(content_type="audio/ogg", content_length=MAX_MEDIA_SIZE_BYTES + 1)

    def test_negative_payload_size_rejected(self):
        with pytest.raises(MediaValidationError, match="Invalid negative Content-Length"):
            validate_media_payload(content_type="audio/ogg", content_length=-1)
