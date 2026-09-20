import logging
import contextvars
from typing import Optional, Dict, Any

from src.platform.telemetry.masking import mask_sensitive_payload, PIIMaskingFilter

# Context variable for distributed tracing correlation
correlation_ctx: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar(
    "correlation_ctx",
    default={}
)


class ContextCorrelationFilter(logging.Filter):
    """
    Injects current distributed tracing context (correlation_id, message_id) into log records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = correlation_ctx.get({})
        record.correlation_id = ctx.get("correlation_id", "none")
        record.message_id = ctx.get("message_id", "none")
        return True


class TelemetryManager:
    """
    Telemetry setup and configuration helper for Application Insights and Log Analytics.
    """

    @classmethod
    def set_trace_context(
        cls,
        correlation_id: str,
        message_id: Optional[str] = None,
        provider_message_id: Optional[str] = None
    ) -> None:
        """Sets the active correlation context for the current async task/thread."""
        ctx = {
            "correlation_id": correlation_id,
            "message_id": message_id or "none",
            "provider_message_id": provider_message_id or "none"
        }
        correlation_ctx.set(ctx)

    @classmethod
    def get_trace_context(cls) -> Dict[str, str]:
        """Gets the active correlation context."""
        return correlation_ctx.get({})

    @classmethod
    def clear_trace_context(cls) -> None:
        """Resets the active correlation context."""
        correlation_ctx.set({})

    @classmethod
    def configure_logging(cls, log_level: int = logging.INFO) -> None:
        """
        Attaches PIIMaskingFilter and ContextCorrelationFilter to the root logger.
        """
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        # Check if filters already added
        has_pii = any(isinstance(f, PIIMaskingFilter) for f in root_logger.filters)
        if not has_pii:
            root_logger.addFilter(PIIMaskingFilter())

        has_corr = any(isinstance(f, ContextCorrelationFilter) for f in root_logger.filters)
        if not has_corr:
            root_logger.addFilter(ContextCorrelationFilter())
