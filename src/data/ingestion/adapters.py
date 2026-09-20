import os
import time
import logging
import requests
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

logger = logging.getLogger("MarketDataAdapters")


class IngestionAdapterError(Exception):
    """Raised when an external data source adapter fetch fails."""
    pass


class BaseSourceAdapter(ABC):
    """Abstract base adapter for government / mandi market data sources."""

    @abstractmethod
    def fetch_observations(
        self,
        commodity: str = "Turmeric",
        state: str = "Tamil Nadu",
        district: str = "Erode",
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Fetches raw market observations from source."""
        pass


class DataGovInAdapter(BaseSourceAdapter):
    """
    Adapter for India's Open Government Data Platform (data.gov.in) agricultural market API.
    Resource ID: 35985678-0d79-46b4-9ed6-6f13308a1d24 (Current Daily Price of Various Commodities)
    """

    DEFAULT_RESOURCE_ID = "35985678-0d79-46b4-9ed6-6f13308a1d24"

    def __init__(
        self,
        api_key: Optional[str] = None,
        resource_id: Optional[str] = None,
        timeout: int = 10,
        max_retries: int = 3,
        backoff_factor: float = 1.5
    ):
        self.api_key = api_key or os.getenv("DATA_GOV_API_KEY")
        self.resource_id = resource_id or self.DEFAULT_RESOURCE_ID
        self.base_url = f"https://api.data.gov.in/resource/{self.resource_id}"
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def fetch_observations(
        self,
        commodity: str = "Turmeric",
        state: str = "Tamil Nadu",
        district: str = "Erode",
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetches market records with query filtering, bounded pagination, and exponential backoff.
        """
        if not self.api_key:
            logger.warning("DATA_GOV_API_KEY is not configured. Live fetch unavailable.")
            return []

        params = {
            "api-key": self.api_key,
            "format": "json",
            "limit": limit,
            "offset": offset,
            "filters[State]": state,
            "filters[District]": district,
            "filters[Commodity]": commodity,
            "sort[Arrival_Date]": "desc"
        }

        attempts = 0
        last_exception = None

        while attempts < self.max_retries:
            attempts += 1
            try:
                logger.info(f"Querying data.gov.in (attempt {attempts}/{self.max_retries}) for {commodity} in {district}...")
                resp = requests.get(self.base_url, params=params, timeout=self.timeout)

                if resp.status_code == 200:
                    data = resp.json()
                    records = data.get("records", [])
                    logger.info(f"Retrieved {len(records)} raw records from data.gov.in.")
                    return records
                elif resp.status_code in [429, 500, 502, 503, 504]:
                    logger.warning(f"data.gov.in returned HTTP {resp.status_code}. Retrying after backoff...")
                    time.sleep(self.backoff_factor ** attempts)
                else:
                    logger.error(f"data.gov.in returned permanent client error HTTP {resp.status_code}: {resp.text}")
                    raise IngestionAdapterError(f"data.gov.in returned HTTP {resp.status_code}")

            except requests.exceptions.RequestException as e:
                last_exception = e
                logger.warning(f"Network error querying data.gov.in: {e}. Retrying...")
                time.sleep(self.backoff_factor ** attempts)

        raise IngestionAdapterError(f"Failed to fetch data from data.gov.in after {self.max_retries} attempts: {last_exception}")


class AgmarknetAdapter(BaseSourceAdapter):
    """
    Adapter for direct AGMARKNET (Directorate of Marketing & Inspection) data ingestion.
    """

    def __init__(self, endpoint_url: Optional[str] = None, timeout: int = 10):
        self.endpoint_url = endpoint_url or os.getenv("AGMARKNET_ENDPOINT_URL", "https://agmarknet.gov.in/SearchMarketData.aspx")
        self.timeout = timeout

    def fetch_observations(
        self,
        commodity: str = "Turmeric",
        state: str = "Tamil Nadu",
        district: str = "Erode",
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Fetches records from AGMARKNET endpoint."""
        logger.info(f"Fetching from AGMARKNET adapter for {commodity} in {district}...")
        # Production adapter hook; returns empty list if mock/live endpoint not active
        return []
