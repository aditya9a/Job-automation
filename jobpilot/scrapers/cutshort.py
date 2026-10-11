"""
Cutshort job scraper.
Scrapes job listings from cutshort.io using Playwright.
"""

import logging
import re
from typing import List
from urllib.parse import urlencode

from .base import BaseScraper
from ..models import Job

logger = logging.getLogger(__name__)


class CutshortScraper(BaseScraper):
    """Scraper for Cutshort.io job listings."""

    platform_name = "cutshort"

    # Verified category URLs for Cutshort (filtered by 0-2 yrs in post-processing)
    TARGET_URLS = [
        "https://cutshort.io/jobs/fullstack-developer-jobs",
        "https://cutshort.io/jobs/backend-developer-jobs",
        "https://cutshort.io/jobs/frontend-developer-jobs",
        "https://cutshort.io/jobs/junior-developer-jobs",
        "https://cutshort.io/jobs/software-development-intern-jobs",
    ]

    async def scrape_jobs(self) -> List[Job]:
        """Scrape jobs from Cutshort across startup directory endpoints."""
        jobs = []
        max_jobs = self.platform_config.get("max_jobs", 50)

        for target_url in self.TARGET_URLS:
            if len(jobs) >= max_jobs:
                break

            for page_num in range(1, min(self.max_pages + 1, 3)):
                url = target_url if page_num == 1 else f"{target_url}?page={page_num}"
                try:
                    logger.info(f"[cutshort] Scraping page {page_num}: {url}")
                    await self.page.goto(url, wait_until="domcontentloaded")
                    await self._random_delay(0.5)

                    # Wait for job links
                    try:
                        await self.page.wait_for_selector('a[href*="/job/"]', timeout=12000)
                    except Exception:
                        logger.warning(f"[cutshort] No job links found on {url}")
                        break

                    page_jobs = await self._extract_jobs_from_page()
                    if not page_jobs:
                        break

                    jobs.extend(page_jobs)
                    logger.info(f"[cutshort] Found {len(page_jobs)} jobs on {url}")

                    if len(jobs) >= max_jobs:
                        break

                except Exception as e:
                    logger.error(f"[cutshort] Error on {url}: {e}")
                    break

        return jobs

    async def _extract_jobs_from_page(self) -> List[Job]:
        """Extract job data from the current page."""
        raw_cards = await self.page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a[href*="/job/"]'));
            const results = [];
            
            for (const link of links) {
                const title = link.innerText.trim();
                const url = link.href;
                if (!title || !url) continue;
                
                // Traverse up to find job card container
                let container = link;
                for (let i = 0; i < 5; i++) {
                    if (container.parentElement) container = container.parentElement;
                }
                
                const lines = container.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
                results.push({
                    title,
                    url,
                    lines
                });
            }
            return results;
        }''')

        jobs = []
        seen_urls = set()

        for r in raw_cards:
            url = r.get("url", "")
            title = r.get("title", "")
            lines = r.get("lines", [])

            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)

            company = "Startup"
            location = ""
            experience = ""
            salary = ""
            skills = []

            meta_idx = -1
            for idx, line in enumerate(lines):
                if line.startswith("at "):
                    company = line[3:].strip()
                elif "·" in line:
                    meta_idx = idx
                    parts = [p.strip() for p in line.split("·")]
                    if len(parts) >= 1:
                        location = parts[0]
                    for p in parts:
                        if "₹" in p or "$" in p or "lpa" in p.lower() or "/ yr" in p.lower():
                            salary = p
                        elif "year" in p.lower() or "yr" in p.lower():
                            experience = p

            if meta_idx != -1 and meta_idx + 1 < len(lines):
                for skill_line in lines[meta_idx + 1:]:
                    low = skill_line.lower()
                    if low in ["apply now", "posted", "candid answers"] or skill_line.startswith("+"):
                        continue
                    if len(skill_line) < 35 and skill_line not in skills:
                        skills.append(skill_line)

            external_id = ""
            match = re.search(r'/job/([a-zA-Z0-9_-]+)', url)
            if match:
                external_id = match.group(1)

            jobs.append(Job(
                title=title,
                company=company,
                platform="cutshort",
                url=url,
                location=location,
                salary=salary,
                experience=experience,
                skills=skills,
                external_id=external_id,
            ))

        return jobs
