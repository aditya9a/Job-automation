"""
Flask Dashboard for JobPilot.
Provides a web UI to view, filter, and manage scraped jobs.
"""

import asyncio
import json
import logging
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from ..database import db
from ..models import JobStatus

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )
    CORS(app)

    # ─── Pages ───────────────────────────────────────────

    @app.route("/")
    def index():
        """Main dashboard page."""
        return render_template("index.html")

    # ─── API Routes ──────────────────────────────────────

    @app.route("/api/jobs")
    def api_jobs():
        """Get jobs with filters."""
        status = request.args.get("status")
        platform = request.args.get("platform")
        min_score = request.args.get("min_score", type=float)
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        search = request.args.get("search", "").strip()

        if search:
            jobs = db.search_jobs(search, limit=limit)
        else:
            jobs = db.get_jobs(
                status=status if status and status != "all" else None,
                platform=platform if platform and platform != "all" else None,
                min_score=min_score,
                limit=limit,
                offset=offset,
            )

        return jsonify({
            "jobs": [j.to_dict() | {"id": j.id} for j in jobs],
            "count": len(jobs),
        })

    @app.route("/api/jobs/<int:job_id>")
    def api_job_detail(job_id):
        """Get a single job's details."""
        job = db.get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(job.to_dict() | {"id": job.id})

    @app.route("/api/jobs/<int:job_id>/status", methods=["POST"])
    def api_update_status(job_id):
        """Update a job's status."""
        data = request.get_json()
        new_status = data.get("status")
        if not new_status:
            return jsonify({"error": "status is required"}), 400

        db.update_job_status(job_id, new_status)
        db.log_application_action(job_id, f"status_change:{new_status}")
        return jsonify({"success": True, "status": new_status})

    @app.route("/api/stats")
    def api_stats():
        """Get dashboard statistics."""
        return jsonify(db.get_stats())

    @app.route("/api/history")
    def api_history():
        """Get scrape history."""
        limit = request.args.get("limit", 20, type=int)
        return jsonify({"history": db.get_scrape_history(limit=limit)})

    @app.route("/api/scrape", methods=["POST"])
    def api_trigger_scrape():
        """Trigger a scrape from the dashboard."""
        data = request.get_json() or {}
        platform = data.get("platform", "all")

        from ..scrapers import SCRAPERS, get_scraper

        platforms_to_scrape = list(SCRAPERS.keys()) if platform == "all" else [platform]

        async def run():
            results = []
            for p in platforms_to_scrape:
                try:
                    scraper = get_scraper(p)
                    result = await scraper.run()
                    results.append({
                        "platform": p,
                        "jobs_found": result.jobs_found,
                        "jobs_new": result.jobs_new,
                        "success": result.success,
                        "errors": result.errors,
                    })
                except Exception as e:
                    results.append({
                        "platform": p,
                        "success": False,
                        "errors": [str(e)],
                    })
            return results

        results = asyncio.run(run())
        return jsonify({"results": results})

    @app.route("/api/match", methods=["POST"])
    def api_trigger_match():
        """Trigger AI matching from the dashboard."""
        try:
            from ..ai.matcher import JobMatcher

            async def run():
                matcher = JobMatcher()
                return await matcher.score_jobs()

            scored = asyncio.run(run())
            return jsonify({"scored": scored})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs/<int:job_id>/cover-letter", methods=["POST"])
    def api_generate_cover_letter(job_id):
        """Generate a cover letter for a job."""
        job = db.get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404

        try:
            from ..ai.matcher import CoverLetterGenerator

            async def run():
                gen = CoverLetterGenerator()
                return await gen.generate(job)

            cover_letter = asyncio.run(run())
            return jsonify({"cover_letter": cover_letter})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/apply", methods=["POST"])
    def api_trigger_apply():
        """Trigger auto-apply from dashboard."""
        data = request.get_json() or {}
        dry_run = data.get("dry_run", False)
        limit = data.get("limit", 20)
        min_score = data.get("min_score", 0)

        try:
            from ..applier.cutshort_applier import CutshortApplier

            async def run():
                applier = CutshortApplier(dry_run=dry_run, daily_limit=limit, min_score=min_score)
                return await applier.run(headless=True)

            res = asyncio.run(run())
            return jsonify(res)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app

