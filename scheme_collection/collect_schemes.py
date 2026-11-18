"""Scheme collection module for SahayAI.

Fetches and ingests welfare scheme datasets from official government portals,
API feeds, or structured scheme registry files. Respects portal rate limits and
access restrictions, never fabricates missing data, and maintains strict separation
between unverified raw intake and verified stores.
"""

from abc import ABC, abstractmethod
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class BaseSchemeSource(ABC):
    """Abstract interface for scheme ingestion sources."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of the data source."""
        pass

    @abstractmethod
    def fetch_schemes(self) -> List[Dict[str, Any]]:
        """Fetch raw scheme records from this source."""
        pass


class LocalFileSchemeSource(BaseSchemeSource):
    """Ingests scheme records from a local verified registry file."""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    @property
    def source_name(self) -> str:
        return f"LocalFile[{self.file_path.name}]"

    def fetch_schemes(self) -> List[Dict[str, Any]]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"Source file not found at: {self.file_path}")

        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(f"Expected a list of scheme records in {self.file_path.name}")

        logger.info("Loaded %d raw schemes from %s", len(data), self.file_path)
        return data


class OfficialAPISchemeSource(BaseSchemeSource):
    """Ingests schemes from an official government REST API endpoint.

    Respects access restrictions, HTTP status codes, and does not attempt to
    bypass server protection mechanisms.
    """

    def __init__(
        self,
        endpoint_url: str,
        api_key: Optional[str] = None,
        timeout: int = 15,
        source_label: str = "OfficialGovAPI",
    ):
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.timeout = timeout
        self._source_label = source_label

    @property
    def source_name(self) -> str:
        parsed = urlparse(self.endpoint_url)
        return f"{self._source_label}[{parsed.netloc}]"

    def fetch_schemes(self) -> List[Dict[str, Any]]:
        import requests

        parsed = urlparse(self.endpoint_url)
        logger.info("Connecting to official scheme API host: %s", parsed.netloc)

        headers = {
            "Accept": "application/json",
            "User-Agent": "SahayAI-OfficialCollector/1.0 (+https://github.com/SahayAI/sahay-ai)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.get(self.endpoint_url, headers=headers, timeout=self.timeout)

            # Check rate limiting or access restrictions
            if response.status_code == 429:
                logger.warning("API endpoint %s reported HTTP 429 Too Many Requests; respecting rate limit.", parsed.netloc)
                raise PermissionError("Rate limit encountered; back-off required.")
            if response.status_code in (401, 403):
                logger.warning("Access restricted on %s (HTTP %d). Not attempting bypass.", parsed.netloc, response.status_code)
                raise PermissionError(f"Access restricted by government portal (HTTP {response.status_code}).")

            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and "schemes" in payload:
                return payload["schemes"]

            raise ValueError("Unexpected API response structure: missing schemes array.")

        except requests.exceptions.RequestException as exc:
            logger.error("Network error connecting to %s: %s", parsed.netloc, exc)
            raise


class SchemeCollector:
    """Coordinates scheme ingestion across configured sources.

    Keeps raw, unverified scheme intake strictly isolated from verified records.
    Never fabricates missing scheme attributes.
    """

    def __init__(self, raw_output_path: Optional[str] = None):
        """Initialize SchemeCollector.

        Args:
            raw_output_path: Destination path for raw unverified schemes.
                             Defaults to 'data/schemes/schemes.json'.
        """
        self.raw_output_path = Path(raw_output_path) if raw_output_path else Path("data/schemes/schemes.json")

    def fetch_from_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Convenience method loading scheme records from a local JSON source registry."""
        source = LocalFileSchemeSource(file_path)
        return source.fetch_schemes()

    def fetch_from_official_api(
        self,
        endpoint_url: str,
        api_key: Optional[str] = None,
        timeout: int = 15,
    ) -> List[Dict[str, Any]]:
        """Convenience method querying an official government API endpoint."""
        source = OfficialAPISchemeSource(endpoint_url, api_key=api_key, timeout=timeout)
        return source.fetch_schemes()

    def ingest_from_source(self, source: BaseSchemeSource) -> List[Dict[str, Any]]:
        """Ingest schemes from a custom BaseSchemeSource implementation."""
        logger.info("Ingesting schemes from source: %s", source.source_name)
        return source.fetch_schemes()

    def save_schemes(self, schemes: List[Dict[str, Any]], target_path: Optional[str] = None) -> Path:
        """Persist collected schemes into the raw unverified store.

        Does not fabricate or inject missing attributes.
        """
        destination = Path(target_path) if target_path else self.raw_output_path
        destination.parent.mkdir(parents=True, exist_ok=True)

        with open(destination, "w", encoding="utf-8") as f:
            json.dump(schemes, f, indent=2, ensure_ascii=False)

        logger.info("Persisted %d raw unverified schemes to %s", len(schemes), destination)
        return destination
