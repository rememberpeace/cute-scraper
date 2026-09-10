import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from scraper import run_scrape, list_jobs, DATA_DIR

app = FastAPI(title="Cute Scraper", version="1.0.0")

STATIC_DIR = Path("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ScrapeRequest(BaseModel):
    url: HttpUrl
    mode: str = "auto"
    max_pages: int = 5


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/jobs")
async def jobs():
    return JSONResponse(list_jobs())


@app.get("/api/download/{job_id}/{fmt}")
async def download(job_id: int, fmt: str):
    jobs_data = list_jobs(200)
    match = next((j for j in jobs_data if j["id"] == job_id), None)
    if not match:
        raise HTTPException(404, "job not found")
    key = "csv_path" if fmt == "csv" else "json_path"
    path = match.get(key)
    if not path or not Path(path).exists():
        raise HTTPException(404, "file not found")
    media = "text/csv" if fmt == "csv" else "application/json"
    return FileResponse(path, media_type=media, filename=Path(path).name)


@app.post("/api/scrape")
async def scrape(req: ScrapeRequest):
    result = await run_scrape(str(req.url), req.mode, req.max_pages)
    return result


@app.websocket("/ws/scrape")
async def ws_scrape(ws: WebSocket):
    await ws.accept()
    try:
        payload = await ws.receive_json()
        url = payload.get("url")
        mode = payload.get("mode", "auto")
        max_pages = int(payload.get("max_pages", 5))

        if not url:
            await ws.send_json({"type": "error", "message": "url required"})
            await ws.close()
            return

        async def progress(msg: str):
            await ws.send_json({"type": "progress", "message": msg})

        await ws.send_json({"type": "start", "url": url})

        result = await run_scrape(url, mode, max_pages, progress)

        await ws.send_json({"type": "done", **result})
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
