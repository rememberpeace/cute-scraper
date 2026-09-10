import asyncio
import json
import csv
import re
import time
import random
import sqlite3
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "jobs.db"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

TEXT_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "span", "a", "div"]
PRICE_RE = re.compile(r"(?:[$€£¥]|USD|EUR|GBP|BAM|KM)\s?\d[\d\.,]*|\d[\d\.,]*\s?(?:USD|EUR|GBP|BAM|KM|kn|din)", re.I)
EMAIL_RE = re.compile(r"[\w\.\-+]+@[\w\-]+\.[\w\.\-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\s\-\(\)]{7,}\d)")
URL_RE = re.compile(r"^https?://", re.I)


def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                rows INTEGER DEFAULT 0,
                mode TEXT,
                created REAL,
                finished REAL,
                csv_path TEXT,
                json_path TEXT
            )
        """)


def record_job(url: str, status: str, mode: Optional[str] = None) -> int:
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO jobs (url, status, mode, created) VALUES (?, ?, ?, ?)",
            (url, status, mode, time.time()),
        )
        return cur.lastrowid


def finish_job(job_id: int, rows: int, csv_path: str, json_path: str):
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            "UPDATE jobs SET status=?, rows=?, finished=?, csv_path=?, json_path=? WHERE id=?",
            ("done", rows, time.time(), csv_path, json_path, job_id),
        )


def fail_job(job_id: int, error: str):
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            "UPDATE jobs SET status=?, finished=? WHERE id=?",
            (f"error: {error[:200]}", time.time(), job_id),
        )


def list_jobs(limit: int = 50):
    with sqlite3.connect(DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


async def fetch_static(url: str, timeout: float = 20.0) -> str:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def fetch_dynamic(url: str, timeout: float = 30000, wait: str = "networkidle") -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        page = await ctx.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        try:
            await page.goto(url, timeout=timeout, wait_until=wait)
        except Exception:
            try:
                await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            except Exception:
                pass
        await page.wait_for_timeout(1200)
        html = await page.content()
        await browser.close()
        return html


async def detect_mode(url: str) -> str:
    try:
        html = await fetch_static(url, timeout=12.0)
        if len(html) < 800:
            return "dynamic"
        soup = BeautifulSoup(html, "lxml")
        body_text = soup.get_text(" ", strip=True)
        if len(body_text) < 200:
            return "dynamic"
        scripts = soup.find_all("script")
        heavy = sum(1 for s in scripts if s.get("src") and any(
            k in (s.get("src") or "") for k in ["react", "vue", "angular", "next", "_app", "chunk"]
        ))
        if heavy >= 2 and len(body_text) < 1500:
            return "dynamic"
        return "static"
    except Exception:
        return "dynamic"


def extract_generic(html: str, base_url: str, max_rows: int = 500):
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    candidates = soup.find_all(["article", "li", "div", "section", "tr"])
    best_block = []
    best_score = 0

    for parent in candidates:
        children = [c for c in parent.find_all(recursive=False) if getattr(c, "name", None)]
        if len(children) < 4:
            continue
        signature = {}
        for ch in children:
            sig = (ch.name, tuple(sorted(ch.get("class") or [])))
            signature[sig] = signature.get(sig, 0) + 1
        score = max(signature.values()) if signature else 0
        if score > best_score and score >= 4:
            best_score = score
            best_block = [ch for ch in children if (ch.name, tuple(sorted(ch.get("class") or []))) in signature and signature[(ch.name, tuple(sorted(ch.get("class") or [])))] == score]

    if not best_block:
        best_block = soup.find_all(["article", "li"], limit=max_rows) or soup.find_all("div", limit=min(max_rows, 100))

    rows = []
    for block in best_block[:max_rows]:
        row = {}
        text = block.get_text(" ", strip=True)
        if not text or len(text) < 5:
            continue

        heading = block.find(["h1", "h2", "h3", "h4"])
        if heading:
            row["title"] = heading.get_text(" ", strip=True)[:300]

        link = block.find("a", href=True)
        if link:
            href = link["href"]
            row["url"] = href if URL_RE.match(href) else urljoin(base_url, href)
            if "title" not in row:
                row["title"] = link.get_text(" ", strip=True)[:300]

        price = PRICE_RE.search(text)
        if price:
            row["price"] = price.group(0).strip()

        email = EMAIL_RE.search(text)
        if email:
            row["email"] = email.group(0)

        phone = PHONE_RE.search(text)
        if phone:
            row["phone"] = phone.group(0).strip()

        img = block.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                row["image"] = src if URL_RE.match(src) else urljoin(base_url, src)

        if "description" not in row:
            desc = text[:500]
            if row.get("title") and desc.startswith(row["title"]):
                desc = desc[len(row["title"]):].strip()
            if desc:
                row["description"] = desc

        if row:
            rows.append(row)

    if not rows:
        paragraphs = soup.find_all("p", limit=max_rows)
        for p in paragraphs:
            t = p.get_text(" ", strip=True)
            if t and len(t) > 20:
                rows.append({"text": t[:800]})

    return rows


async def paginate(url: str, mode: str, max_pages: int, progress_cb=None):
    all_rows = []
    seen = set()
    current = url
    page_num = 1

    while current and page_num <= max_pages:
        if progress_cb:
            await progress_cb(f"page {page_num}: {current}")

        try:
            if mode == "dynamic":
                html = await fetch_dynamic(current)
            else:
                html = await fetch_static(current)
        except Exception as e:
            if progress_cb:
                await progress_cb(f"page {page_num} failed: {e}")
            break

        rows = extract_generic(html, current)
        added = 0
        for r in rows:
            key = json.dumps(r, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                all_rows.append(r)
                added += 1

        if progress_cb:
            await progress_cb(f"page {page_num}: +{added} rows ({len(all_rows)} total)")

        if added == 0 and page_num > 1:
            break

        soup = BeautifulSoup(html, "lxml")
        next_url = None
        for a in soup.find_all("a", href=True):
            label = (a.get_text(" ", strip=True) or "").lower()
            rel = (a.get("rel") or [])
            if isinstance(rel, str):
                rel = [rel]
            if "next" in rel or label in {"next", "next page", "›", "»", "→", "sljedeća", "dalje"}:
                href = a["href"]
                next_url = href if URL_RE.match(href) else urljoin(current, href)
                break

        if not next_url or next_url == current:
            break

        current = next_url
        page_num += 1
        await asyncio.sleep(random.uniform(0.6, 1.4))

    return all_rows


def save_outputs(rows, base_name: str):
    csv_path = DATA_DIR / f"{base_name}.csv"
    json_path = DATA_DIR / f"{base_name}.json"

    if rows:
        keys = []
        for r in rows:
            for k in r.keys():
                if k not in keys:
                    keys.append(k)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    return str(csv_path), str(json_path)


def slugify(url: str) -> str:
    host = urlparse(url).netloc.replace(":", "_")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{host}_{stamp}"


async def run_scrape(url: str, mode: str, max_pages: int, progress_cb=None):
    job_id = record_job(url, "running", mode)
    try:
        if mode == "auto":
            mode = await detect_mode(url)
            if progress_cb:
                await progress_cb(f"detected mode: {mode}")

        rows = await paginate(url, mode, max_pages, progress_cb)
        name = slugify(url)
        csv_path, json_path = save_outputs(rows, name)
        finish_job(job_id, len(rows), csv_path, json_path)
        return {
            "job_id": job_id,
            "rows": len(rows),
            "csv": csv_path,
            "json": json_path,
            "mode": mode,
        }
    except Exception as e:
        fail_job(job_id, str(e))
        raise


init_db()
