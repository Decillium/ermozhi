import pytest
import datetime
import asyncio
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from src.channels.meta.client import MetaWhatsAppClient, MetaDeliveryError


class TestMetaWhatsAppOutbound:

    def test_format_whatsapp_text(self):
        client = MetaWhatsAppClient()
        raw = "**வணக்கம்** உழவரே! விலை: **₹14,500** / குவிண்டால்."
        formatted = client.format_whatsapp_text(raw)
        assert "*வணக்கம்*" in formatted
        assert "*₹14,500*" in formatted
        assert "**" not in formatted

    def test_within_24h_window_true(self):
        client = MetaWhatsAppClient()
        recent = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat()
        assert client.is_within_24h_window(recent) is True

    def test_outside_24h_window_false(self):
        client = MetaWhatsAppClient()
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=26)).isoformat()
        assert client.is_within_24h_window(old) is False

    def test_simulation_mode_when_no_token(self):
        client = MetaWhatsAppClient(access_token=None)
        res = asyncio.run(client.send_message(
            to_phone="+919876543210",
            text="சோதனை செய்தி",
            media_url="https://marketstorage.blob.core.windows.net/media/test.mp3"
        ))
        assert res["status"] == "ACCEPTED"
        assert res["mode"] == "simulation"
        assert len(res["provider_message_ids"]) == 2  # Text + Audio in simulation

    def test_dual_dispatch_within_24h_window_with_mock_http(self):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        
        # Responses for text and audio POSTs
        mock_resp_text = MagicMock()
        mock_resp_text.status_code = 200
        mock_resp_text.json.return_value = {"messages": [{"id": "wamid.HBgLMTIzNDU2Nw=="}]}
        
        mock_resp_audio = MagicMock()
        mock_resp_audio.status_code = 200
        mock_resp_audio.json.return_value = {"messages": [{"id": "wamid.HBgLODk5OTk5OQ=="}]}

        mock_http.post.side_effect = [mock_resp_text, mock_resp_audio]

        client = MetaWhatsAppClient(
            phone_number_id="1000123456",
            access_token="EAAX_valid_meta_token",
            http_client=mock_http
        )

        res = asyncio.run(client.send_message(
            to_phone="919876543210",
            text="விலை பரிந்துரை: விற்கவும்",
            media_url="https://marketstorage.blob.core.windows.net/media/audio.mp3",
            inbound_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            idempotency_key="test_idem_123"
        ))

        assert res["status"] == "ACCEPTED"
        assert res["within_24h_window"] is True
        assert len(res["provider_message_ids"]) == 2
        assert res["provider_message_ids"][0] == "wamid.HBgLMTIzNDU2Nw=="
        assert res["provider_message_ids"][1] == "wamid.HBgLODk5OTk5OQ=="

        assert mock_http.post.call_count == 2
        # Verify text payload
        call_text = mock_http.post.call_args_list[0]
        assert call_text.kwargs["json"]["type"] == "text"
        assert call_text.kwargs["json"]["text"]["body"] == "விலை பரிந்துரை: விற்கவும்"
        
        # Verify audio payload
        call_audio = mock_http.post.call_args_list[1]
        assert call_audio.kwargs["json"]["type"] == "audio"
        assert call_audio.kwargs["json"]["audio"]["link"] == "https://marketstorage.blob.core.windows.net/media/audio.mp3"

    def test_template_dispatch_outside_24h_window(self):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "wamid.HBgLTU9DSw=="}]}
        mock_http.post.return_value = mock_resp

        client = MetaWhatsAppClient(
            phone_number_id="1000123456",
            access_token="EAAX_valid_meta_token",
            http_client=mock_http
        )

        old_timestamp = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=30)).isoformat()
        res = asyncio.run(client.send_message(
            to_phone="919876543210",
            text="விலை தகவல்",
            template_name="price_result_ta",
            template_params=[{"type": "text", "text": "Finger"}, {"type": "text", "text": "14500"}],
            inbound_timestamp=old_timestamp
        ))

        assert res["status"] == "ACCEPTED"
        assert res["within_24h_window"] is False
        assert len(res["provider_message_ids"]) == 1
        
        # Verify template payload
        call_tpl = mock_http.post.call_args_list[0]
        assert call_tpl.kwargs["json"]["type"] == "template"
        assert call_tpl.kwargs["json"]["template"]["name"] == "price_result_ta"

    def test_retry_on_429_rate_limit(self):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "0.01"}
        mock_429.text = "Rate limit exceeded"

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"messages": [{"id": "wamid.success_after_retry"}]}

        mock_http.post.side_effect = [mock_429, mock_200]

        client = MetaWhatsAppClient(
            phone_number_id="1000123456",
            access_token="EAAX_valid_meta_token",
            http_client=mock_http
        )

        res = asyncio.run(client.send_message(to_phone="919876543210", text="சோதனை"))
        assert res["status"] == "ACCEPTED"
        assert mock_http.post.call_count == 2

    def test_non_retryable_400_error(self):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        
        mock_400 = MagicMock()
        mock_400.status_code = 400
        mock_400.text = "Invalid phone number"
        mock_400.json.return_value = {"error": {"message": "Invalid recipient"}}

        mock_http.post.return_value = mock_400

        client = MetaWhatsAppClient(
            phone_number_id="1000123456",
            access_token="EAAX_valid_meta_token",
            http_client=mock_http
        )

        with pytest.raises(MetaDeliveryError) as exc_info:
            asyncio.run(client.send_message(to_phone="invalid_phone", text="சோதனை"))

        assert exc_info.value.status_code == 400
        assert exc_info.value.retryable is False
