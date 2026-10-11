"""
JobPilot CLI — Command-line interface.
Usage: python -m jobpilot <command>
"""

import asyncio
import logging
import sys
import os

# Fix Windows console encoding for emoji/unicode
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from .config import settings
from .database import db
from .models import JobStatus

console = Console()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0", prog_name="JobPilot")
def cli():
    """🚀 JobPilot — Semi-Automated Job Application Assistant"""
    pass


@cli.command()
@click.option("--platform", "-p", type=click.Choice(["cutshort", "wellfound", "hirist", "linkedin", "all"]),
              default="all", help="Platform to scrape")
@click.option("--headless/--no-headless", default=True, help="Run browser in headless mode")
def scrape(platform, headless):
    """🔍 Scrape jobs from platforms."""
    from .scrapers import get_scraper, SCRAPERS

    platforms_to_scrape = list(SCRAPERS.keys()) if platform == "all" else [platform]

    console.print(Panel.fit(
        f"[bold cyan]🔍 Scraping jobs from: {', '.join(platforms_to_scrape)}[/bold cyan]",
        border_style="cyan"
    ))

    async def run_scrapers():
        results = []
        for p in platforms_to_scrape:
            try:
                console.print(f"\n[yellow]▸ Starting {p} scraper...[/yellow]")
                scraper = get_scraper(p)
                result = await scraper.run(headless=headless)
                results.append(result)

                if result.success:
                    console.print(
                        f"  [green]✓ {p}: {result.jobs_found} found, "
                        f"{result.jobs_new} new, {result.jobs_duplicate} duplicates[/green]"
                    )
                else:
                    console.print(f"  [red]✗ {p}: Failed — {', '.join(result.errors)}[/red]")
            except Exception as e:
                console.print(f"  [red]✗ {p}: Error — {e}[/red]")

        return results

    results = asyncio.run(run_scrapers())

    # Summary table
    console.print("\n")
    table = Table(title="📊 Scrape Summary", show_header=True, header_style="bold magenta")
    table.add_column("Platform", style="cyan")
    table.add_column("Found", justify="right")
    table.add_column("New", justify="right", style="green")
    table.add_column("Duplicates", justify="right", style="yellow")
    table.add_column("Status", justify="center")

    for r in results:
        status = "✅" if r.success else "❌"
        table.add_row(r.platform, str(r.jobs_found), str(r.jobs_new), str(r.jobs_duplicate), status)

    console.print(table)


@cli.command()
@click.option("--limit", "-l", default=50, help="Max jobs to score")
def match(limit):
    """🤖 Run AI matching on unscored jobs."""
    from .ai.matcher import JobMatcher

    console.print(Panel.fit(
        "[bold cyan]🤖 Running AI Job Matching (Gemini)[/bold cyan]",
        border_style="cyan"
    ))

    async def run_matching():
        matcher = JobMatcher()
        unmatched = db.get_jobs(status=JobStatus.NEW.value, limit=limit)

        if not unmatched:
            console.print("[yellow]No unmatched jobs found. Run 'scrape' first.[/yellow]")
            return 0

        console.print(f"[cyan]Scoring {len(unmatched)} jobs...[/cyan]\n")

        scored = 0
        for job in unmatched:
            try:
                result = await matcher.score_job(job)
                score = result["score"]
                reason = result["reason"]

                full_reason = reason
                if result["strengths"]:
                    full_reason += f" Strengths: {', '.join(result['strengths'])}."
                if result["gaps"]:
                    full_reason += f" Gaps: {', '.join(result['gaps'])}."

                db.update_match_score(job.id, score, full_reason)
                scored += 1

                # Color-coded score display
                color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
                console.print(
                    f"  [{color}]{score:3d}%[/{color}] "
                    f"[white]{job.title}[/white] @ [cyan]{job.company}[/cyan] "
                    f"— {reason}"
                )
            except Exception as e:
                console.print(f"  [red]Error scoring {job.title}: {e}[/red]")

        return scored

    scored = asyncio.run(run_matching())
    console.print(f"\n[green]✓ Scored {scored} jobs[/green]")


@cli.command()
@click.option("--status", "-s", type=click.Choice(["new", "matched", "shortlisted", "applied", "all"]),
              default="matched", help="Filter by status")
@click.option("--platform", "-p", default=None, help="Filter by platform")
@click.option("--min-score", "-m", type=float, default=None, help="Minimum match score")
@click.option("--limit", "-l", default=30, help="Max jobs to show")
def jobs(status, platform, min_score, limit):
    """📋 List scraped jobs."""
    status_filter = None if status == "all" else status
    job_list = db.get_jobs(
        status=status_filter,
        platform=platform,
        min_score=min_score,
        limit=limit,
    )

    if not job_list:
        console.print("[yellow]No jobs found with the given filters.[/yellow]")
        return

    table = Table(
        title=f"📋 Jobs ({len(job_list)} results)",
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("ID", style="dim", width=5)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Title", style="white", max_width=35)
    table.add_column("Company", style="cyan", max_width=20)
    table.add_column("Platform", width=10)
    table.add_column("Location", max_width=15)
    table.add_column("Status", width=12)

    for j in job_list:
        score_color = "green" if j.match_score >= 70 else "yellow" if j.match_score >= 50 else "red"
        score_str = f"[{score_color}]{j.match_score:.0f}%[/{score_color}]" if j.match_score > 0 else "—"
        table.add_row(
            str(j.id), score_str, j.title, j.company,
            j.platform, j.location, j.status
        )

    console.print(table)


@cli.command()
def stats():
    """📊 Show database statistics."""
    s = db.get_stats()

    console.print(Panel.fit(
        "[bold cyan]📊 JobPilot Statistics[/bold cyan]",
        border_style="cyan"
    ))

    console.print(f"  Total jobs:        [bold]{s['total_jobs']}[/bold]")
    console.print(f"  New today:         [bold green]{s['today_new']}[/bold green]")
    console.print(f"  Avg match score:   [bold]{s['avg_match_score']}%[/bold]")

    if s["by_status"]:
        console.print("\n  [bold]By Status:[/bold]")
        for status, count in s["by_status"].items():
            console.print(f"    {status}: {count}")

    if s["by_platform"]:
        console.print("\n  [bold]By Platform:[/bold]")
        for platform, count in s["by_platform"].items():
            console.print(f"    {platform}: {count}")


@cli.command()
@click.option("--port", "-p", default=None, type=int, help="Dashboard port")
def dashboard(port):
    """🌐 Launch the web dashboard."""
    from .dashboard.app import create_app

    port = port or settings.dashboard_port
    host = settings.dashboard_host

    console.print(Panel.fit(
        f"[bold cyan]🌐 Starting Dashboard at http://{host}:{port}[/bold cyan]",
        border_style="cyan"
    ))

    app = create_app()
    app.run(host=host, port=port, debug=True)


@cli.command(name="run-daily")
def run_daily():
    """🔄 Run the full daily pipeline (scrape → match → notify)."""
    console.print(Panel.fit(
        "[bold cyan]🔄 Running Full Daily Pipeline[/bold cyan]",
        border_style="cyan"
    ))

    # Step 1: Scrape
    console.print("\n[bold]Step 1/3: Scraping...[/bold]")
    from .scrapers import SCRAPERS, get_scraper

    async def pipeline():
        # Scrape all platforms
        total_new = 0
        for p in SCRAPERS:
            try:
                scraper = get_scraper(p)
                result = await scraper.run()
                total_new += result.jobs_new
                status = "✅" if result.success else "❌"
                console.print(f"  {status} {p}: {result.jobs_new} new jobs")
            except Exception as e:
                console.print(f"  ❌ {p}: {e}")

        console.print(f"\n  [green]Total new jobs: {total_new}[/green]")

        # Step 2: AI Matching
        if total_new > 0:
            console.print("\n[bold]Step 2/3: AI Matching...[/bold]")
            try:
                from .ai.matcher import JobMatcher
                matcher = JobMatcher()
                scored = await matcher.score_jobs()
                console.print(f"  [green]✓ Scored {scored} jobs[/green]")
            except Exception as e:
                console.print(f"  [red]AI matching error: {e}[/red]")
        else:
            console.print("\n[bold]Step 2/3: AI Matching...[/bold] [yellow]Skipped (no new jobs)[/yellow]")

        # Step 3: Summary
        console.print("\n[bold]Step 3/3: Summary[/bold]")
        s = db.get_stats()
        high_matches = db.get_jobs(status=JobStatus.MATCHED.value, min_score=70, limit=10)

        if high_matches:
            console.print(f"\n  🎯 [bold green]{len(high_matches)} high-scoring matches (70%+):[/bold green]")
            for j in high_matches:
                console.print(f"    • {j.match_score:.0f}% — {j.title} @ {j.company}")
        else:
            console.print("  [yellow]No high-scoring matches today.[/yellow]")

    asyncio.run(pipeline())
    console.print("\n[green bold]✅ Daily pipeline complete![/green bold]")


@cli.command()
@click.option("--time", "-t", default="09:00", help="Time to run daily (HH:MM)")
def schedule(time):
    """⏰ Schedule daily automatic runs."""
    from .scheduler import start_scheduler

    console.print(Panel.fit(
        f"[bold cyan]⏰ Scheduling daily run at {time}[/bold cyan]",
        border_style="cyan"
    ))

    start_scheduler(time)


@cli.command()
@click.option("--platform", "-p", type=click.Choice(["cutshort"]), default="cutshort", help="Platform to log in to")
def login(platform):
    """🔐 Log in to a platform interactively (one-time) and save your session."""
    from .applier.cutshort_applier import CutshortApplier

    console.print(Panel.fit(
        f"[bold cyan]🔐 One-Time Interactive Login: {platform.title()}[/bold cyan]\n"
        "[dim]This opens a browser for you to log in with Google or Phone OTP.\n"
        "Your session is saved so future auto-applies run seamlessly in the background.[/dim]",
        border_style="cyan"
    ))

    async def do_login():
        applier = CutshortApplier()
        return await applier.interactive_login()

    success = asyncio.run(do_login())
    if success:
        console.print("[bold green]✅ Login successful! You are ready to auto-apply.[/bold green]")
    else:
        console.print("[yellow]Session saved. You can test applying with --dry-run.[/yellow]")


@cli.command()
@click.option("--platform", "-p", type=click.Choice(["cutshort", "all"]), default="cutshort", help="Platform to apply to")
@click.option("--dry-run/--live", default=False, help="Dry run mode (simulate clicks without submitting)")
@click.option("--limit", "-l", default=20, type=int, help="Maximum jobs to apply for")
@click.option("--min-score", "-m", default=0, type=float, help="Minimum match score (0 to apply to all)")
@click.option("--min-exp", default=None, type=float, help="Minimum experience in years (default from profile)")
@click.option("--max-exp", default=None, type=float, help="Maximum experience in years (default 2.0)")
@click.option("--headless/--no-headless", default=True, help="Run browser in headless mode")
def apply(platform, dry_run, limit, min_score, min_exp, max_exp, headless):
    """🚀 Automatically apply to scraped jobs."""
    from .applier.cutshort_applier import CutshortApplier

    min_e = min_exp if min_exp is not None else settings.min_experience_years
    max_e = max_exp if max_exp is not None else settings.max_experience_years

    mode_label = "[yellow]DRY RUN[/yellow]" if dry_run else "[bold green]LIVE APPLY[/bold green]"
    console.print(Panel.fit(
        f"[bold cyan]🚀 Job Auto-Applier: {platform.title()} ({mode_label})[/bold cyan]\n"
        f"[dim]Max jobs: {limit} | Min score: {min_score}% | Exp: {min_e:g}-{max_e:g} yrs | Headless: {headless}[/dim]",
        border_style="cyan"
    ))

    async def do_apply():
        applier = CutshortApplier(
            dry_run=dry_run,
            daily_limit=limit,
            min_score=min_score,
            min_experience=min_e,
            max_experience=max_e
        )
        return await applier.run(headless=headless)

    res = asyncio.run(do_apply())

    console.print("\n")
    table = Table(title="📊 Auto-Apply Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")

    table.add_row("Applied Successfully", str(res.get("applied", 0)))
    table.add_row("Already Applied", str(res.get("already_applied", 0)))
    table.add_row("Failed / Skipped", str(res.get("failed", 0)))

    console.print(table)

    if res.get("jobs"):
        console.print("\n[bold]Job Details:[/bold]")
        for j in res["jobs"]:
            status_icon = "✅" if j["success"] else "❌"
            console.print(f"  {status_icon} [white]{j['title']}[/white] @ [cyan]{j['company']}[/cyan] — {j['message']}")


if __name__ == "__main__":
    cli()

