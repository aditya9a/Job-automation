"""
Wellfound (formerly AngelList) job scraper.
Scrapes startup job listings using Playwright.
"""

import logging
import re
from typing import List

from .base import BaseScraper
from ..models import Job

logger = logging.getLogger(__name__)


class WellfoundScraper(BaseScraper):
    """Scraper for Wellfound.com (AngelList Talent) job listings."""

    platform_name = "wellfound"

    def _build_search_url(self) -> str:
        """Build the Wellfound search URL."""
        base = self.platform_config.get("search_url", "https://wellfound.com/jobs")
        return base

    async def scrape_jobs(self) -> List[Job]:
        """Scrape jobs from Wellfound."""
        jobs = []

        try:
            url = self._build_search_url()
            logger.info(f"[wellfound] Navigating to {url}")

            await self.page.goto(url, wait_until="domcontentloaded")
            await self._random_delay(0.5)

            # Wellfound may show a cookie/signup modal — dismiss it
            await self._dismiss_modals()

            for page_num in range(1, self.max_pages + 1):
                logger.info(f"[wellfound] Scraping page {page_num}")

                # Wait for job listings
                try:
                    await self.page.wait_for_selector(
                        '[class*="styles_jobCard"], [class*="JobCard"], '
                        '[data-test="StartupResult"], a[href*="/jobs/"]',
                        timeout=15000
                    )
                except Exception:
                    logger.warning(f"[wellfound] No job cards found on page {page_num}")
                    break

                page_jobs = await self._extract_jobs_from_page()
                if not page_jobs:
                    break

                jobs.extend(page_jobs)
                logger.info(f"[wellfound] Page {page_num}: found {len(page_jobs)} jobs")

                if len(jobs) >= self.platform_config.get("max_jobs", 50):
                    break

                # Scroll to load more (Wellfound uses infinite scroll)
                has_more = await self._scroll_for_more()
                if not has_more:
                    break

        except Exception as e:
            logger.error(f"[wellfound] Scrape error: {e}", exc_info=True)

        return jobs

    async def _dismiss_modals(self):
        """Dismiss any popups/modals that might appear."""
        try:
            # Close cookie consent
            for selector in [
                'button:has-text("Accept")',
                'button:has-text("Got it")',
                'button:has-text("Close")',
                '[aria-label="Close"]',
                'button:has-text("Dismiss")',
            ]:
                btn = await self.page.query_selector(selector)
                if btn:
                    await btn.click()
                    await self._random_delay(0.3)
        except Exception:
            pass

    async def _extract_jobs_from_page(self) -> List[Job]:
        """Extract job listings from the current page state."""
        jobs = []

        # Wellfound has a nested structure: startup cards containing job listings
        selectors = [
            '[class*="styles_jobCard"]',
            '[class*="JobCard"]',
            '[data-test="StartupResult"]',
            '[class*="job-listing"]',
        ]

        cards = []
        for selector in selectors:
            cards = await self.page.query_selector_all(selector)
            if cards:
                break

        # Fallback: parse all job links
        if not cards:
            cards = await self.page.query_selector_all('a[href*="/jobs/"]')

        for card in cards:
            try:
                job = await self._parse_job_card(card)
                if job and job.title:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"[wellfound] Error parsing card: {e}")
                continue

        return jobs

    async def _parse_job_card(self, card) -> Job:
        """Parse a Wellfound job card into a Job object."""
        # Title
        title_el = await card.query_selector(
            'h2, h3, h4, [class*="title"], [class*="Title"], '
            '[class*="jobTitle"], [class*="role"]'
        )
        title = await title_el.inner_text() if title_el else ""
        title = title.strip()
        if not title:
            # Try getting text from an anchor
            text = await card.inner_text()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            title = lines[0] if lines else ""

        if not title:
            return None

        # Company
        company_el = await card.query_selector(
            '[class*="company"], [class*="Company"], [class*="startup"], '
            '[class*="Startup"], [class*="brandName"]'
        )
        company = await company_el.inner_text() if company_el else "Unknown Startup"

        # URL
        link_el = await card.query_selector('a[href*="/jobs/"], a[href*="/role/"]')
        if not link_el:
            href = await card.get_attribute("href")
            if href and "/jobs/" in href:
                link_el = card

        url = ""
        if link_el:
            href = await link_el.get_attribute("href")
            if href:
                url = href if href.startswith("http") else f"https://wellfound.com{href}"

        # Location
        location_el = await card.query_selector(
            '[class*="location"], [class*="Location"]'
        )
        location = await location_el.inner_text() if location_el else ""

        # Salary
        salary_el = await card.query_selector(
            '[class*="salary"], [class*="Salary"], [class*="compensation"]'
        )
        salary = await salary_el.inner_text() if salary_el else ""

        # Skills
        skill_els = await card.query_selector_all(
            '[class*="skill"], [class*="tag"], [class*="chip"]'
        )
        skills = []
        for el in skill_els:
            text = await el.inner_text()
            if text.strip():
                skills.append(text.strip())

        # External ID from URL
        external_id = ""
        if url:
            match = re.search(r'/jobs/(\d+)', url)
            if not match:
                match = re.search(r'/role/([a-zA-Z0-9_-]+)', url)
            if match:
                external_id = match.group(1)

        return Job(
            title=title.strip(),
            company=company.strip(),
            platform="wellfound",
            url=url or f"https://wellfound.com/jobs#{title}",
            location=location.strip(),
            salary=salary.strip(),
            skills=skills,
            external_id=external_id,
            job_type="full_time",
        )

    async def _scroll_for_more(self) -> bool:
        """Scroll down to trigger infinite scroll loading."""
        try:
            prev_height = await self.page.evaluate("document.body.scrollHeight")
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._random_delay(1.5)
            new_height = await self.page.evaluate("document.body.scrollHeight")
            return new_height > prev_height
        except Exception:
            return False
