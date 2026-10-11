# 🚀 JobPilot — Semi-Automated Job Application Assistant

A Python-based job automation tool that scrapes, filters, and helps you apply to jobs on **Cutshort**, **Wellfound**, **Hirist**, and **LinkedIn**.

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│   Job Scrapers   │───▶│  AI Matcher &    │───▶│  Auto-Filler    │───▶│  Web Dashboard   │
│  (per platform)  │    │  Ranker (Gemini) │    │  (Playwright)   │    │  (Flask + JS)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └──────────────────┘
```

## Features

- **Multi-platform scraping**: Cutshort, Wellfound, Hirist, LinkedIn
- **AI-powered matching**: Uses Google Gemini to match jobs against your resume
- **Semi-automatic applying**: Fills forms but pauses for your review before submitting
- **Smart deduplication**: Never shows you the same job twice
- **Web dashboard**: Track all jobs, review matches, manage applications
- **Daily scheduler**: Runs automatically on a schedule

## Setup

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium

# 4. Configure your profile
# Edit config/profile.yaml with your details
# Place your resume at config/resume.pdf

# 5. Set up environment variables
copy .env.example .env
# Edit .env with your Gemini API key

# 6. Run the scraper
python -m jobpilot scrape

# 7. Launch the dashboard
python -m jobpilot dashboard
```

## Project Structure

```
job automation/
├── jobpilot/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── config.py            # Configuration loader
│   ├── database.py          # SQLite database layer
│   ├── models.py            # Data models
│   ├── scheduler.py         # Daily job scheduler
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py          # Base scraper class
│   │   ├── cutshort.py      # Cutshort scraper
│   │   ├── wellfound.py     # Wellfound scraper
│   │   ├── hirist.py        # Hirist scraper
│   │   └── linkedin.py      # LinkedIn scraper
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── matcher.py       # Job-resume matching
│   │   └── generator.py     # Cover letter / response generation
│   ├── applier/
│   │   ├── __init__.py
│   │   ├── base.py          # Base auto-applier
│   │   └── form_filler.py   # Generic form filling logic
│   └── dashboard/
│       ├── __init__.py
│       ├── app.py           # Flask app
│       ├── static/
│       │   ├── css/
│       │   │   └── style.css
│       │   └── js/
│       │       └── app.js
│       └── templates/
│           └── index.html
├── config/
│   ├── profile.yaml         # Your profile & preferences
│   └── platforms.yaml       # Platform-specific settings
├── .env.example
├── requirements.txt
└── README.md
```

## Usage

### CLI Commands

```bash
# Scrape jobs from all platforms
python -m jobpilot scrape

# Scrape from a specific platform
python -m jobpilot scrape --platform linkedin

# Run AI matching on scraped jobs
python -m jobpilot match

# Launch the web dashboard
python -m jobpilot dashboard

# Run the full daily pipeline
python -m jobpilot run-daily

# Schedule daily runs
python -m jobpilot schedule --time 09:00
```
