"""
Hirist job scraper.
Scrapes tech job listings from hirist.tech using Playwright.
"""

import logging
import re
from typing import List

from .base import BaseScraper
from ..models import Job

logger = logging.getLogger(__name__)


class HiristScraper(BaseScraper):
    """Scraper for Hirist.tech — a premium tech jobs portal."""

    platform_name = "hirist"

    # Known categories on Hirist matching software engineering
    CATEGORIES = [
        "backend-development-jobs",
        "frontend-development-jobs",
        "mobile-development-jobs",
        "devops-jobs",
    ]

    def _build_search_url(self, category: str, page_num: int = 1) -> str:
        """Build Hirist category URL."""
        base = "https://www.hirist.tech/c"
        url = f"{base}/{category}"
        if page_num > 1:
            url += f"?page={page_num}"
        return url

    async def scrape_jobs(self) -> List[Job]:
        """Scrape jobs from Hirist across relevant engineering categories."""
        jobs = []
        max_jobs = self.platform_config.get("max_jobs", 50)

        for category in self.CATEGORIES:
            if len(jobs) >= max_jobs:
                break

            for page_num in range(1, min(self.max_pages + 1, 3)):
                try:
                    url = self._build_search_url(category, page_num)
                    logger.info(f"[hirist] Scraping {category} (page {page_num}): {url}")
                    await self.page.goto(url, wait_until="domcontentloaded")
                    await self._random_delay(0.5)

                    # Wait for job listing cards
                    try:
                        await self.page.wait_for_selector('a[href*="/j/"]', timeout=10000)
                    except Exception:
                        logger.warning(f"[hirist] No job cards found for {category}")
                        break

                    page_jobs = await self._extract_jobs_from_page()
                    if not page_jobs:
                        break

                    jobs.extend(page_jobs)
                    logger.info(f"[hirist] {category} page {page_num}: found {len(page_jobs)} jobs")

                    if len(jobs) >= max_jobs:
                        break

                except Exception as e:
                    logger.error(f"[hirist] Error scraping {category}: {e}")
                    break

        return jobs

    async def _extract_jobs_from_page(self) -> List[Job]:
        """Extract job data from the current page."""
        jobs = []
        cards = await self.page.query_selector_all('a[href*="/j/"]')

        for card in cards:
            try:
                job = await self._parse_job_card(card)
                if job and job.title:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"[hirist] Error parsing card: {e}")
                continue

        return jobs

    async def _parse_job_card(self, card) -> Job:
        """Parse a Hirist job card into a Job object."""
        # Title (via data-testid or fallback)
        title_el = await card.query_selector(
            '[data-testid="job_title"], h2, h3, [class*="title"]'
        )
        title = await title_el.inner_text() if title_el else ""
        title = title.strip()

        if not title:
            text = await card.inner_text()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            title = lines[0] if lines else ""

        if not title:
            return None

        # Experience
        exp_el = await card.query_selector(
            '[data-testid="job_experience"], [class*="exp"]'
        )
        experience = await exp_el.inner_text() if exp_el else ""

        # Location
        location_el = await card.query_selector(
            '[data-testid="job_location"], [class*="location"]'
        )
        location = await location_el.inner_text() if location_el else ""

        # Skills & Tags
        tag_els = await card.query_selector_all(
            '[data-testid^="job_tag_"], [class*="skill"], [class*="tag"]'
        )
        skills = []
        for el in tag_els:
            t = await el.inner_text()
            if t.strip() and t.strip() not in skills:
                skills.append(t.strip())

        # Company parsing
        # Often title is in form: "Company - Job Title"
        company = "Hirist Partner"
        if " - " in title:
            parts = title.split(" - ")
            if len(parts) >= 2 and len(parts[0]) <= 30:
                company = parts[0].strip()

        # URL
        href = await card.get_attribute("href")
        url = ""
        if href:
            url = href if href.startswith("http") else f"https://www.hirist.tech{href}"

        # External ID
        external_id = ""
        if url:
            match = re.search(r'[-/](\d+)', url)
            if match:
                external_id = match.group(1)

        return Job(
            title=title.strip(),
            company=company.strip(),
            platform="hirist",
            url=url or f"https://www.hirist.tech/jobs#{title}",
            location=location.strip(),
            salary="",
            experience=experience.strip(),
            skills=skills,
            external_id=external_id,
        )
