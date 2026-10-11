"""
Cutshort Auto-Applier
Automates applying to jobs on Cutshort using Playwright.
Supports persistent session login, resume upload, modal handling, and database tracking.
"""

import asyncio
import logging
import os
import random
from pathlib import Path
from typing import List, Optional, Tuple

from playwright.async_api import async_playwright, BrowserContext, Page
from fake_useragent import UserAgent

from ..config import settings
from ..database import db
from ..models import Job, JobStatus

logger = logging.getLogger(__name__)

SESSION_DIR = Path("data/cutshort_profile")


class CutshortApplier:
    """
    Automated Cutshort job applier.

    Flow:
    1. Launch browser with persistent session (preserves Google/OTP login)
    2. Check login status (or prompt interactive login if needed)
    3. For each candidate job: navigate to job URL -> click Apply -> handle modal / upload -> confirm
    4. Record application status in database
    """

    HOME_URL = "https://cutshort.io"
    LOGIN_URL = "https://cutshort.io"
    
    APPLY_BUTTON_SELECTORS = [
        'button:has-text("Apply to this job")',
        'button:has-text("Apply now")',
        'button:has-text("Apply Now")',
        'a:has-text("Apply to this job")',
        'a:has-text("Apply now")',
        '[class*="apply"]:has-text("Apply")',
        'button[data-testid*="apply"]',
    ]

    MODAL_CONFIRM_SELECTORS = [
        'button:has-text("Confirm")',
        'button:has-text("Submit")',
        'button:has-text("Send application")',
        'button:has-text("Yes, apply")',
        'button:has-text("Next")',
        '[class*="modal"] button:has-text("Apply")',
    ]

    def __init__(
        self,
        dry_run: bool = False,
        daily_limit: int = 30,
        min_score: float = 0,
        min_experience: Optional[float] = None,
        max_experience: Optional[float] = None
    ):
        self.dry_run = dry_run
        self.daily_limit = daily_limit
        self.min_score = min_score
        self.min_experience = min_experience if min_experience is not None else settings.min_experience_years
        self.max_experience = max_experience if max_experience is not None else settings.max_experience_years
        self.ua = UserAgent()
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._playwright = None

    async def _random_delay(self, min_s: float = 1.5, max_s: float = 3.5):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def start_browser(self, headless: bool = True):
        """Launch browser with persistent profile storage to retain login sessions."""
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()

        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR.resolve()),
            headless=headless,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.set_default_timeout(25000)
        logger.info(f"[applier] Browser started (headless={headless}, session={SESSION_DIR})")

    async def stop_browser(self):
        """Close browser context."""
        try:
            if self.context:
                await self.context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug(f"[applier] Error stopping browser: {e}")
        logger.info("[applier] Browser stopped")

    async def is_logged_in(self) -> bool:
        """Check if currently logged in to Cutshort."""
        try:
            await self.page.goto(self.HOME_URL, wait_until="domcontentloaded")
            await self._random_delay(1.5, 2.5)

            # Look for Candidate login button
            candidate_login_btn = await self.page.query_selector(
                'button:has-text("Candidate login"), a:has-text("Candidate login")'
            )
            if not candidate_login_btn:
                # If Candidate login is NOT present, user is likely logged in
                logger.info("[applier] Session verified: Already logged in to Cutshort")
                return True

            body_text = await self.page.inner_text("body")
            email = os.getenv("CUTSHORT_EMAIL", "")
            if email and email.split("@")[0].lower() in body_text.lower():
                return True

            return False
        except Exception as e:
            logger.warning(f"[applier] Could not determine login status: {e}")
            return False

    async def interactive_login(self) -> bool:
        """
        Open a visible browser window for the user to log in once via Google or Phone OTP.
        Saves session cookies to data/cutshort_profile for future headless runs.
        """
        await self.start_browser(headless=False)
        print("\n" + "=" * 60)
        print("🔐 CUTSHORT INTERACTIVE LOGIN")
        print("Opening Cutshort in your browser...")
        print("Please log in using your Google account or Phone OTP.")
        print("=" * 60 + "\n")

        await self.page.goto(self.HOME_URL, wait_until="domcontentloaded")
        await self._random_delay(1.0, 2.0)

        # Click Candidate login if visible
        try:
            btn = await self.page.query_selector('button:has-text("Candidate login")')
            if btn and await btn.is_visible():
                await btn.click()
        except Exception:
            pass

        print("👉 Complete your login in the browser window.")
        print("👉 Press ENTER in this console once you are logged in...")

        # Run non-blocking input wait in executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sys_input_wait)

        # Verify
        logged_in = await self.is_logged_in()
        if logged_in:
            print("\n✅ Successfully authenticated! Session saved to data/cutshort_profile.\n")
        else:
            print("\n⚠️ Login could not be verified, but session data has been saved.\n")

        await self.stop_browser()
        return logged_in

    async def apply_to_job(self, job: Job) -> Tuple[bool, str]:
        """Navigate to a job page and execute full apply flow. Returns (success, message)."""
        if not job.url:
            return False, "No URL"

        # Check experience eligibility (e.g. 0-2 years)
        is_ok, exp_reason = job.is_experience_eligible(self.min_experience, self.max_experience)
        if not is_ok:
            logger.info(f"[applier] Skipping {job.title} ({job.experience}): {exp_reason}")
            return False, f"Experience filtered: {exp_reason}"

        try:
            logger.info(f"[applier] Visiting {job.url}")
            await self.page.goto(job.url, wait_until="domcontentloaded")
            await self._random_delay(2.0, 3.5)

            page_text = (await self.page.inner_text("body")).lower()

            if "already applied" in page_text or "you have applied" in page_text:
                return False, "Already applied"

            if "error 404" in page_text or "could not find your page" in page_text:
                return False, "Job expired / closed (404)"

            # Step 1: Find visible Apply button on public page
            apply_btn = None
            buttons = await self.page.query_selector_all("button, a")
            for b in buttons:
                txt = (await b.inner_text()).strip().lower()
                if "apply to this job" in txt or txt == "apply now":
                    is_vis = await b.is_visible()
                    bbox = await b.bounding_box()
                    if is_vis and bbox and bbox["y"] > 0:
                        apply_btn = b
                        break

            # Fallback selector search
            if not apply_btn:
                for sel in self.APPLY_BUTTON_SELECTORS:
                    try:
                        b = await self.page.query_selector(sel)
                        if b and await b.is_visible():
                            apply_btn = b
                            break
                    except Exception:
                        continue

            if not apply_btn:
                if "applied" in page_text:
                    return False, "Already applied"
                return False, "Apply button not found"

            # Click initial Apply button on public job page
            try:
                await apply_btn.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                await apply_btn.click(force=True)
            except Exception:
                # Element may be outside viewport - use JS click
                logger.debug("[applier] Using JS click for Apply button (outside viewport)")
                await apply_btn.evaluate("el => el.click()")

            # Wait for portal redirect or modal to appear
            await self._random_delay(3.0, 5.0)

            # Step 2: Check if redirected to Candidate Portal (/profile/all-jobs?jobid=...)
            current_url = self.page.url
            if "profile" in current_url or "all-jobs" in current_url or "jobid=" in current_url:
                logger.info("[applier] Candidate portal view detected. Proceeding with portal application...")
                return await self._handle_candidate_portal_flow(job)

            # Step 3: Handle guest resume upload modal if present
            await self._handle_resume_upload_if_needed()

            # Step 4: Handle modal confirmation buttons on public page
            confirmed = await self._handle_apply_modal()

            await self._random_delay(1.5, 2.5)

            # Verify application result
            new_page_text = (await self.page.inner_text("body")).lower()
            success_keywords = [
                "application sent", "applied successfully", "you have applied",
                "application submitted", "thank you for applying", "applied",
                "your application has been sent"
            ]
            if any(kw in new_page_text for kw in success_keywords):
                return True, "Application confirmed"

            if confirmed:
                return True, "Apply clicked & confirmed"

            return True, "Apply clicked"

        except Exception as e:
            logger.error(f"[applier] Error applying to {job.title}: {e}")
            return False, f"Error: {e}"

    async def _handle_candidate_portal_flow(self, job: Job) -> Tuple[bool, str]:
        """
        Execute candidate portal application (/profile/all-jobs?jobid=...):
        1. Wait for the portal job card to load
        2. Click 'Apply now' on the portal job card → opens modal with textarea + Send button
        3. Fill intro message in textarea[name="message"]
        4. Click 'Send' to submit application to recruiter
        5. Verify confirmation
        """
        try:
            # Wait for the portal job card to render
            try:
                await self.page.wait_for_selector(
                    'button:has-text("Apply now"), button:has-text("Send")',
                    timeout=10000
                )
            except Exception:
                await self._random_delay(2.0, 3.0)

            portal_body = (await self.page.inner_text("body")).lower()

            if "already applied" in portal_body or "you have applied" in portal_body:
                return False, "Already applied on portal"

            if "no jobs found" in portal_body:
                return False, "Job not available in portal (expired or already applied)"

            # 1. Check if the Send modal is already open
            send_check = await self.page.query_selector('button:has-text("Send")')
            if send_check and await send_check.is_visible():
                logger.info("[applier] Send modal already open, skipping Apply now click")
            else:
                # Find and click portal 'Apply now' button on the job card
                portal_apply_btn = None
                all_buttons = await self.page.query_selector_all("button")
                for b in all_buttons:
                    try:
                        txt = (await b.inner_text()).strip().lower()
                        vis = await b.is_visible()
                        if vis and txt == "apply now":
                            portal_apply_btn = b
                            break
                    except Exception:
                        continue

                if not portal_apply_btn:
                    return False, "Portal 'Apply now' button not found on job card"

                logger.info("[applier] Clicking portal 'Apply now' to open application modal...")
                try:
                    await portal_apply_btn.scroll_into_view_if_needed()
                    await portal_apply_btn.click()
                except Exception:
                    await portal_apply_btn.evaluate("el => el.click()")

                # Wait for the modal to open (contains textarea + Send button)
                try:
                    await self.page.wait_for_selector(
                        '[role="dialog"], .modal__wrapper, textarea[name="message"]',
                        timeout=8000
                    )
                except Exception:
                    await self._random_delay(2.0, 3.0)

            # 2. Find the message textarea inside the modal
            textarea = await self.page.query_selector(
                'textarea[name="message"], textarea[placeholder="Type your message..."], '
                '[role="dialog"] textarea, .modal__wrapper textarea'
            )
            if textarea and await textarea.is_visible():
                intro_msg = (
                    "Hi! I am excited to apply for this role. "
                    "My background in Full Stack development (React, Node.js, Express, MongoDB, "
                    "Java, Python, AWS) aligns well with your requirements. "
                    "Looking forward to discussing this opportunity!"
                )
                logger.info("[applier] Filling intro message in application modal...")
                try:
                    await textarea.click()
                    await textarea.fill(intro_msg)
                    await self._random_delay(0.5, 1.0)
                except Exception as e:
                    logger.debug(f"[applier] Textarea fill: {e}")
            else:
                logger.debug("[applier] No message textarea found in modal (will proceed without message)")

            # 3. Find and click 'Send' button inside the modal
            send_btn = None
            all_buttons2 = await self.page.query_selector_all("button")
            for b in all_buttons2:
                try:
                    txt = (await b.inner_text()).strip().lower()
                    vis = await b.is_visible()
                    if vis and txt == "send":
                        send_btn = b
                        break
                except Exception:
                    continue

            # Fallback selector
            if not send_btn:
                send_btn = await self.page.query_selector(
                    '[role="dialog"] button:has-text("Send"), .modal__wrapper button:has-text("Send")'
                )

            if not send_btn or not await send_btn.is_visible():
                logger.warning("[applier] Send button not visible in modal")
                return False, "Send button not found in application modal"

            if self.dry_run:
                logger.info("[applier] DRY RUN: Would click Send button now")
                return True, "DRY RUN: Application modal ready with Send button"

            logger.info("[applier] Clicking 'Send' to submit application...")
            try:
                await send_btn.click()
            except Exception:
                await send_btn.evaluate("el => el.click()")

            await self._random_delay(3.0, 5.0)

            # 4. Verify confirmation — modal closes or success text appears
            try:
                modal_still_open = await self.page.query_selector('[role="dialog"]')
                if not modal_still_open or not await modal_still_open.is_visible():
                    return True, "Application sent (modal closed after Send)"
            except Exception:
                return True, "Application sent"

            after_text = (await self.page.inner_text("body")).lower()
            if any(kw in after_text for kw in [
                "sent", "applied", "application sent", "submitted",
                "in conversation", "thank you"
            ]):
                return True, "Application sent successfully"

            return True, "Application sent (Send clicked)"

        except Exception as e:
            logger.error(f"[applier] Error in portal application flow: {e}")
            return False, f"Portal apply error: {e}"


    async def _handle_resume_upload_if_needed(self):
        """Upload resume if file input is presented."""
        try:
            file_input = await self.page.query_selector('input[type="file"]')
            resume_path = Path("config/resume.pdf").resolve()
            if file_input and resume_path.exists():
                logger.info(f"[applier] Uploading resume from {resume_path}...")
                await file_input.set_input_files(str(resume_path))
                await self._random_delay(1.0, 2.0)

                # Click Next or Upload resume button
                next_btn = await self.page.query_selector(
                    'button:has-text("Next"), button:has-text("Upload resume")'
                )
                if next_btn and await next_btn.is_visible():
                    await next_btn.click()
                    await self._random_delay(1.0, 2.0)
        except Exception as e:
            logger.debug(f"[applier] Resume upload check: {e}")

    async def _handle_apply_modal(self) -> bool:
        """Handle post-apply confirmation modals."""
        confirmed = False
        try:
            for sel in self.MODAL_CONFIRM_SELECTORS:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    logger.info(f"[applier] Clicking modal confirm button: {sel}")
                    await btn.click()
                    await self._random_delay(1.0, 2.0)
                    confirmed = True
                    break
        except Exception as e:
            logger.debug(f"[applier] Modal handling: {e}")
        return confirmed

    async def run(self, headless: bool = True) -> dict:
        """Full auto-apply pipeline for Cutshort jobs."""
        results = {
            "applied": 0,
            "failed": 0,
            "already_applied": 0,
            "jobs": []
        }

        try:
            await self.start_browser(headless=headless)

            # Check authentication
            logged_in = await self.is_logged_in()
            if not logged_in:
                logger.warning(
                    "[applier] Not logged in to Cutshort. "
                    "Running with resume auto-upload mode. "
                    "To log in once, run: python -m jobpilot login --platform cutshort"
                )

            jobs = self._get_jobs_to_apply()
            if not jobs:
                results["message"] = "No new Cutshort jobs to apply for"
                return results

            mode = "DRY RUN" if self.dry_run else "LIVE"
            logger.info(f"[applier] [{mode}] Processing {len(jobs)} jobs...")

            for i, job in enumerate(jobs):
                if results["applied"] >= self.daily_limit:
                    logger.info(f"[applier] Daily limit ({self.daily_limit}) reached.")
                    break

                logger.info(f"[applier] [{i+1}/{len(jobs)}] {job.title} @ {job.company}")

                success, message = await self.apply_to_job(job)

                results["jobs"].append({
                    "id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "url": job.url,
                    "success": success,
                    "message": message,
                })

                if success:
                    results["applied"] += 1
                    if not self.dry_run:
                        db.update_job_status(job.id, JobStatus.APPLIED.value)
                        db.log_application(job_id=job.id, action="applied", notes=message)
                    logger.info(f"[applier]   ✓ SUCCESS: {message}")
                elif "already applied" in message.lower():
                    results["already_applied"] += 1
                    if not self.dry_run:
                        db.update_job_status(job.id, JobStatus.APPLIED.value)
                    logger.info(f"[applier]   ⊘ SKIP: {message}")
                else:
                    results["failed"] += 1
                    if not self.dry_run:
                        db.log_application(job_id=job.id, action="apply_failed", notes=message)
                    logger.warning(f"[applier]   ✗ FAIL: {message}")

                # Human-like delay between job applications
                await self._random_delay(3.0, 6.0)

        except Exception as e:
            logger.error(f"[applier] Fatal error: {e}")
            results["error"] = str(e)
        finally:
            await self.stop_browser()

        return results

    def _get_jobs_to_apply(self) -> List[Job]:
        """Get Cutshort jobs that are eligible to apply."""
        jobs = []
        for status in ["new", "matched"]:
            batch = db.get_jobs(platform="cutshort", status=status, limit=self.daily_limit * 2)
            jobs.extend(batch)

        if self.min_score > 0:
            jobs = [j for j in jobs if j.match_score >= self.min_score]

        seen = set()
        unique = []
        for j in jobs:
            if j.id not in seen:
                seen.add(j.id)
                # Check experience filter (e.g. 0-2 years)
                ok, reason = j.is_experience_eligible(self.min_experience, self.max_experience)
                if ok:
                    unique.append(j)
                else:
                    logger.info(f"[applier] Excluded job #{j.id} '{j.title}' ({j.experience}): {reason}")

        logger.info(f"[applier] {len(unique)} candidate jobs match experience filter ({self.min_experience}-{self.max_experience} yrs)")
        return unique[:self.daily_limit]


def sys_input_wait():
    """Helper to wait for user input in non-async thread."""
    try:
        input()
    except Exception:
        pass
