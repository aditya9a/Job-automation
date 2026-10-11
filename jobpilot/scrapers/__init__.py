"""Scrapers package."""

from .base import BaseScraper
from .cutshort import CutshortScraper
from .wellfound import WellfoundScraper
from .hirist import HiristScraper
from .linkedin import LinkedInScraper

SCRAPERS = {
    "cutshort": CutshortScraper,
    "wellfound": WellfoundScraper,
    "hirist": HiristScraper,
    "linkedin": LinkedInScraper,
}


def get_scraper(platform: str) -> BaseScraper:
    """Factory: get a scraper instance by platform name."""
    scraper_class = SCRAPERS.get(platform.lower())
    if not scraper_class:
        raise ValueError(f"Unknown platform: {platform}. Available: {list(SCRAPERS.keys())}")
    return scraper_class()
