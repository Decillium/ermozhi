import logging
import pytest
from src.platform.telemetry import (
    mask_phone_number,
    mask_sensitive_payload,
    PIIMaskingFilter,
    TelemetryManager,
    ContextCorrelationFilter
)


class TestTelemetryAndPIIMasking:

    def test_mask_phone_number_formats(self):
        assert mask_phone_number("+919876543210") == "+91XXXXXX3210"
        assert mask_phone_number("9876543210") == "XXXXXX3210"
        assert mask_phone_number("whatsapp:+919876543210") == "+91XXXXXX3210"
        assert mask_phone_number("வணக்கம் 9876543210 விலை") == "வணக்கம் XXXXXX3210 விலை"

    def test_mask_sensitive_payload_dict(self):
        payload = {
            "access_token": "EAAX_secret_token_value_123",
            "participant_ref": "+919876543210",
            "audio_bytes": b"binary_audio_data_here",
            "metadata": {
                "user_phone": "9876543210",
                "app_secret": "my_super_secret",
                "status": "active"
            }
        }

        masked = mask_sensitive_payload(payload)

        assert masked["access_token"] == "[REDACTED_SECRET]"
        assert masked["participant_ref"] == "+91XXXXXX3210"
        assert masked["audio_bytes"] == "<bytes len=22>"
        assert masked["metadata"]["user_phone"] == "XXXXXX3210"
        assert masked["metadata"]["app_secret"] == "[REDACTED_SECRET]"
        assert masked["metadata"]["status"] == "active"

    def test_pii_masking_log_filter(self):
        log_filter = PIIMaskingFilter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Farmer with phone +919876543210 submitted query",
            args=(),
            exc_info=None
        )

        assert log_filter.filter(record) is True
        assert "+91XXXXXX3210" in record.msg
        assert "+919876543210" not in record.msg

    def test_context_correlation_filter(self):
        TelemetryManager.set_trace_context(
            correlation_id="corr_test_999",
            message_id="msg_test_888"
        )

        corr_filter = ContextCorrelationFilter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=20,
            msg="Processing message",
            args=(),
            exc_info=None
        )

        assert corr_filter.filter(record) is True
        assert record.correlation_id == "corr_test_999"
        assert record.message_id == "msg_test_888"

        TelemetryManager.clear_trace_context()
        assert TelemetryManager.get_trace_context() == {}
