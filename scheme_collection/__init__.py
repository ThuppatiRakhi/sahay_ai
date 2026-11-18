"""Scheme Collection Package for SahayAI.

Handles scraping, collection, validation, and multi-stage verification of government welfare schemes.
"""

from .collect_schemes import BaseSchemeSource, LocalFileSchemeSource, OfficialAPISchemeSource, SchemeCollector
from .scheme_discovery_service import SchemeDiscoveryService
from .scheme_validator import SchemeModel, SchemeValidator
from .verify_schemes import SchemeVerificationReport, SchemeVerifier

__all__ = [
    "BaseSchemeSource",
    "LocalFileSchemeSource",
    "OfficialAPISchemeSource",
    "SchemeCollector",
    "SchemeDiscoveryService",
    "SchemeModel",
    "SchemeValidator",
    "SchemeVerificationReport",
    "SchemeVerifier",
]
