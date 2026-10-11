"""
Base scraper class.
All platform-specific scrapers inherit from this.
"""

import asyncio
import random
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from fake_useragent import UserAgent

from ..config import settings
from ..models import Job, ScrapeResult
from ..database import db

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Abstract base scraper. Provides shared functionality:
    - Browser lifecycle management (Playwright)
    - Random delays for anti-detection
    - User agent rotation
    - Error handling & retries
    - Deduplication via database
    """

    platform_name: str = "base"

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.ua = UserAgent()
        self.platform_config = self._get_platform_config()

    def _get_platform_config(self) -> dict:
        """Get config for this specific platform."""
        platforms = settings.platforms.get("platforms", {})
        return platforms.get(self.platform_name, {})

    @property
    def is_enabled(self) -> bool:
        return self.platform_config.get("enabled", False)

    @property
    def max_pages(self) -> int:
        return self.platform_config.get("max_pages", 5)

    @property
    def delay_seconds(self) -> int:
        return self.platform_config.get("delay_seconds", 3)

    async def _random_delay(self, multiplier: float = 1.0):
        """Wait a random amount of time to mimic human behavior."""
        base = self.delay_seconds
        delay = random.uniform(base * 0.7, base * 1.5) * multiplier
        await asyncio.sleep(delay)

    async def start_browser(self, headless: Optional[bool] = None):
        """Launch a Playwright browser instance."""
        scraping_config = settings.platforms.get("scraping", {})
        if headless is None:
            headless = scraping_config.get("headless", True)

        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )

        # Create context with random user agent
        user_agent = self.ua.random
        self.context = await self.browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )

        # Add stealth scripts to avoid detection
        await self.context.add_init_script("""
            // Override webdriver property
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            
            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)

        self.page = await self.context.new_page()
        self.page.set_default_timeout(
            scraping_config.get("timeout_seconds", 30) * 1000
        )
        logger.info(f"[{self.platform_name}] Browser started (headless={headless})")

    async def stop_browser(self):
        """Close the browser."""
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info(f"[{self.platform_name}] Browser stopped")

    @abstractmethod
    async def scrape_jobs(self) -> List[Job]:
        """
        Scrape jobs from the platform.
        Must be implemented by each platform-specific scraper.
        Returns a list of Job objects.
        """
        pass

    async def login(self) -> bool:
        """
        Optional login step for platforms that require authentication.
        Override in subclass if needed. Returns True if login successful.
        """
        return True

    def _filter_by_preferences(self, jobs: List[Job]) -> List[Job]:
        """
        Pre-filter jobs based on user preferences (exclude keywords, etc.)
        This is a quick filter before AI matching.
        """
        filtered = []
        exclude = [kw.lower() for kw in settings.exclude_keywords]

        # Build include keywords from target roles (only for cutshort where sidebar noise is high)
        include_role_keywords = [kw.lower() for kw in [
            "software", "developer", "engineer", "fullstack", "full stack", "full-stack",
            "backend", "frontend", "web developer", "sde", "swe", "react", "node",
            "python", "java", "technical", "devops", "cloud", "data engineer",
            "mobile", "android", "ios", "api", "microservice",
        ]]

        for job in jobs:
            title_lower = job.title.lower()
            desc_lower = job.description.lower()

            # Check exclude keywords
            excluded = False
            for kw in exclude:
                if kw in title_lower or kw in desc_lower:
                    excluded = True
                    break

            if excluded:
                continue

            # For cutshort, apply role-relevance filter to avoid sidebar noise
            if self.platform_name == "cutshort":
                is_relevant = any(kw in title_lower for kw in include_role_keywords)
                if not is_relevant:
                    continue

            # Check experience eligibility (e.g. 0-2 years)
            ok, exp_reason = job.is_experience_eligible(
                min_allowed=settings.min_experience_years,
                max_allowed=settings.max_experience_years
            )
            if not ok:
                logger.debug(f"[{self.platform_name}] Filtered out '{job.title}' ({job.experience}): {exp_reason}")
                continue

            filtered.append(job)

        removed = len(jobs) - len(filtered)
        if removed > 0:
            logger.info(f"[{self.platform_name}] Filtered out {removed} jobs by preferences (keywords & experience)")
        return filtered


    async def run(self, headless: Optional[bool] = None) -> ScrapeResult:
        """
        Full scrape pipeline:
        1. Start browser
        2. Login (if needed)
        3. Scrape jobs
        4. Filter by preferences
        5. Save to database (with dedup)
        6. Log results
        """
        result = ScrapeResult(platform=self.platform_name)

        if not self.is_enabled:
            logger.warning(f"[{self.platform_name}] Platform is disabled in config")
            result.success = False
            result.errors.append("Platform disabled")
            result.finish()
            return result

        try:
            await self.start_browser(headless=headless)

            # Login if needed
            logged_in = await self.login()
            if not logged_in:
                result.success = False
                result.errors.append("Login failed")
                result.finish()
                return result

            # Scrape
            logger.info(f"[{self.platform_name}] Starting scrape...")
            jobs = await self.scrape_jobs()
            result.jobs_found = len(jobs)
            logger.info(f"[{self.platform_name}] Found {len(jobs)} jobs")

            # Filter
            jobs = self._filter_by_preferences(jobs)

            # Save to database
            inserted, duplicates = db.add_jobs(jobs)
            result.jobs_new = inserted
            result.jobs_duplicate = duplicates
            logger.info(
                f"[{self.platform_name}] Saved: {inserted} new, {duplicates} duplicates"
            )

        except Exception as e:
            logger.error(f"[{self.platform_name}] Scrape error: {e}", exc_info=True)
            result.success = False
            result.errors.append(str(e))
        finally:
            await self.stop_browser()
            result.finish()

            # Log to database
            db.log_scrape(
                platform=result.platform,
                jobs_found=result.jobs_found,
                jobs_new=result.jobs_new,
                jobs_duplicate=result.jobs_duplicate,
                errors=result.errors,
                started_at=result.started_at,
                completed_at=result.completed_at,
                success=result.success,
            )

        return result
