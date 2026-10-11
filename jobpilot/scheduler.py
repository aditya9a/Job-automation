"""
Daily scheduler for JobPilot.
Runs the scrape → match pipeline on a schedule.
"""

import logging
import schedule
import time
import asyncio

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


def _run_daily_pipeline():
    """Execute the daily pipeline."""
    from .scrapers import SCRAPERS, get_scraper
    from .database import db
    from .models import JobStatus

    async def pipeline():
        total_new = 0
        for platform_name in SCRAPERS:
            try:
                scraper = get_scraper(platform_name)
                result = await scraper.run()
                total_new += result.jobs_new
                logger.info(f"[scheduler] {platform_name}: {result.jobs_new} new jobs")
            except Exception as e:
                logger.error(f"[scheduler] {platform_name} error: {e}")

        # AI matching
        if total_new > 0:
            try:
                from .ai.matcher import JobMatcher
                matcher = JobMatcher()
                scored = await matcher.score_jobs()
                logger.info(f"[scheduler] Scored {scored} jobs")
            except Exception as e:
                logger.error(f"[scheduler] Matching error: {e}")

        # Log summary
        stats = db.get_stats()
        logger.info(
            f"[scheduler] Pipeline complete. "
            f"Total: {stats['total_jobs']}, Today new: {stats['today_new']}, "
            f"Avg score: {stats['avg_match_score']}%"
        )

    asyncio.run(pipeline())


def start_scheduler(run_time: str = "09:00"):
    """
    Start the daily scheduler.
    
    Args:
        run_time: Time to run daily in HH:MM format (24-hour)
    """
    schedule.every().day.at(run_time).do(_run_daily_pipeline)

    console.print(f"[green]✓ Scheduler started. Will run daily at {run_time}[/green]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped.[/yellow]")
