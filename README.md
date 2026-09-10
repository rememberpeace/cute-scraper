# Cute Scraper

A clean, self-hosted web scraper with a modern UI. Paste a URL, get structured data back as CSV or JSON.

## Features

- Auto-detects static HTML vs JavaScript-rendered pages
- Follows pagination automatically
- Retries with backoff, user-agent rotation, polite delays
- Live progress streamed to the UI via WebSocket
- Clean CSV and JSON export
- Job history stored in SQLite
- Zero build step — plain HTML, CSS, and JS

## Stack

- **FastAPI** + **Uvicorn** — backend server
- **Playwright** — headless Chromium for JS-heavy pages
- **BeautifulSoup** + **lxml** — fast static HTML parsing
- **SQLite** — job log

## Requirements

- Python 3.11, 3.12, or 3.13
- ~200MB disk for the Chromium download

## Install

```bash
git clone https://github.com/rememberpeace/cute-scraper.git
cd cute-scraper

python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000

## Usage

1. Paste a URL into the input
2. Choose mode — `Auto-detect`, `Static`, or `Dynamic`
3. Set max pages
4. Click **Scrape**
5. Download CSV or JSON from the result panel

Outputs are saved to `data/` and logged in `data/jobs.db`.

## Project structure

```
cute-scraper/
├── main.py            FastAPI app + routes
├── scraper.py         scraping engine
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── requirements.txt
└── data/              (created at runtime, gitignored)
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/`                        | UI |
| POST   | `/api/scrape`              | Run a scrape (blocking) |
| WS     | `/ws/scrape`               | Run a scrape (streaming progress) |
| GET    | `/api/jobs`                | List recent jobs |
| GET    | `/api/download/{id}/{fmt}` | Download CSV or JSON |

## License

MIT
