"""
LinkedIn job scraper.
Scrapes job listings from LinkedIn, focusing on Easy Apply jobs.
Uses login-based scraping for better results.
"""

import logging
import re
from typing import List
from urllib.parse import urlencode

from .base import BaseScraper
from ..models import Job
from ..config import settings

logger = logging.getLogger(__name__)


class LinkedInScraper(BaseScraper):
    """
    Scraper for LinkedIn job listings.
    
    IMPORTANT: LinkedIn has aggressive anti-bot detection.
    This scraper uses conservative delays and human-like behavior.
    Use at your own risk — excessive automation may result in account restrictions.
    """

    platform_name = "linkedin"

    def _build_search_url(self, start: int = 0) -> str:
        """Build LinkedIn job search URL with filters."""
        base = "https://www.linkedin.com/jobs/search/"
        roles = settings.user_roles
        locations = settings.user_locations

        params = {
            "keywords": roles[0] if roles else "Software Engineer",
            "location": locations[0] if locations else "India",
            "f_AL": "true",  # Easy Apply only
            "f_E": "1,2",    # Entry level + Internship
            "sortBy": "DD",  # Date posted (most recent)
            "start": start,
        }

        # Add Easy Apply filter if configured
        if self.platform_config.get("easy_apply_only", True):
            params["f_AL"] = "true"

        return f"{base}?{urlencode(params)}"

    async def login(self) -> bool:
        """Log into LinkedIn."""
        email = settings.linkedin_email
        password = settings.linkedin_password

        if not email or not password:
            logger.warning(
                "[linkedin] No credentials configured. "
                "Scraping public listings only (limited results)."
            )
            return True  # Continue without login

        try:
            logger.info("[linkedin] Logging in...")
            await self.page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            await self._random_delay(0.5)

            # Fill email
            await self.page.fill('#username', email)
            await self._random_delay(0.3)

            # Fill password
            await self.page.fill('#password', password)
            await self._random_delay(0.3)

            # Click sign in
            await self.page.click('button[type="submit"]')
            await self._random_delay(2.0)

            # Check if login was successful
            current_url = self.page.url
            if "feed" in current_url or "mynetwork" in current_url or "jobs" in current_url:
                logger.info("[linkedin] Login successful")
                return True

            # Check for security challenge
            if "checkpoint" in current_url or "challenge" in current_url:
                logger.warning(
                    "[linkedin] Security challenge detected! "
                    "Please complete the verification manually or use a different approach."
                )
                return False

            logger.warning(f"[linkedin] Login may have failed. Current URL: {current_url}")
            return True  # Try to continue anyway

        except Exception as e:
            logger.error(f"[linkedin] Login error: {e}")
            return False

    async def scrape_jobs(self) -> List[Job]:
        """Scrape jobs from LinkedIn."""
        jobs = []
        jobs_per_page = 25  # LinkedIn shows 25 jobs per page

        for page_num in range(self.max_pages):
            try:
                start = page_num * jobs_per_page
                url = self._build_search_url(start=start)
                logger.info(f"[linkedin] Scraping page {page_num + 1} (start={start})")

                await self.page.goto(url, wait_until="domcontentloaded")
                await self._random_delay(1.5)

                # Wait for job cards
                try:
                    await self.page.wait_for_selector(
                        '.job-card-container, .jobs-search-results__list-item, '
                        '[class*="job-card"], .base-card',
                        timeout=15000
                    )
                except Exception:
                    logger.warning(f"[linkedin] No job cards found on page {page_num + 1}")
                    break

                # Scroll through the results to load all cards
                await self._scroll_job_list()

                page_jobs = await self._extract_jobs_from_page()
                if not page_jobs:
                    break

                jobs.extend(page_jobs)
                logger.info(f"[linkedin] Page {page_num + 1}: found {len(page_jobs)} jobs")

                if len(jobs) >= self.platform_config.get("max_jobs", 50):
                    break

                await self._random_delay(1.5)

            except Exception as e:
                logger.error(f"[linkedin] Error on page {page_num + 1}: {e}")
                continue

        return jobs

    async def _scroll_job_list(self):
        """Scroll through the job list to load all visible cards."""
        try:
            for _ in range(3):
                await self.page.evaluate("""
                    const list = document.querySelector('.jobs-search-results-list, .scaffold-layout__list');
                    if (list) list.scrollTop = list.scrollHeight;
                    else window.scrollTo(0, document.body.scrollHeight);
                """)
                await self._random_delay(0.5)
        except Exception:
            pass

    async def _extract_jobs_from_page(self) -> List[Job]:
        """Extract job listings from the current page."""
        jobs = []

        selectors = [
            '.job-card-container',
            '.jobs-search-results__list-item',
            '.base-card',
            '[class*="job-card"]',
        ]

        cards = []
        for selector in selectors:
            cards = await self.page.query_selector_all(selector)
            if cards:
                break

        for card in cards:
            try:
                job = await self._parse_job_card(card)
                if job and job.title:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"[linkedin] Error parsing card: {e}")
                continue

        return jobs

    async def _parse_job_card(self, card) -> Job:
        """Parse a LinkedIn job card into a Job object."""
        # Title
        title_el = await card.query_selector(
            '.job-card-list__title, .base-search-card__title, '
            '[class*="job-title"], h3 a, h3'
        )
        title = await title_el.inner_text() if title_el else ""
        title = title.strip()

        if not title:
            return None

        # Company
        company_el = await card.query_selector(
            '.job-card-container__primary-description, '
            '.base-search-card__subtitle, [class*="company"], h4 a, h4'
        )
        company = await company_el.inner_text() if company_el else "Unknown"

        # URL
        link_el = await card.query_selector('a[href*="/jobs/view/"], a[href*="/jobs/"]')
        if not link_el:
            link_el = await card.query_selector('a')

        url = ""
        if link_el:
            href = await link_el.get_attribute("href")
            if href:
                # Clean tracking parameters
                url = href.split("?")[0]
                if not url.startswith("http"):
                    url = f"https://www.linkedin.com{url}"

        # Location
        location_el = await card.query_selector(
            '.job-card-container__metadata-item, '
            '.job-search-card__location, [class*="location"]'
        )
        location = await location_el.inner_text() if location_el else ""

        # Easy Apply badge
        easy_apply_el = await card.query_selector(
            '[class*="easy-apply"], .job-card-container__apply-method'
        )
        job_type = "easy_apply" if easy_apply_el else "standard"

        # Posted date
        date_el = await card.query_selector(
            'time, [class*="listed-date"], [class*="posted"], [datetime]'
        )
        posted_date = ""
        if date_el:
            posted_date = await date_el.get_attribute("datetime") or await date_el.inner_text()

        # External ID from URL
        external_id = ""
        if url:
            match = re.search(r'/jobs/view/(\d+)', url)
            if match:
                external_id = match.group(1)

        return Job(
            title=title.strip(),
            company=company.strip(),
            platform="linkedin",
            url=url or f"https://www.linkedin.com/jobs#{title}",
            location=location.strip(),
            posted_date=posted_date.strip(),
            job_type=job_type,
            external_id=external_id,
        )
