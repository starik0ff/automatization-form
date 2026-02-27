import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from worker import BotWorker
from email_reader import test_imap_connection

BASE_DIR = Path(__file__).parent

app = FastAPI(title="FB Form Bot")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

STATUS_FILE  = BASE_DIR / "status.json"
STATS_FILE   = BASE_DIR / "stats.json"

bot_worker: Optional[BotWorker] = None
bot_thread:  Optional[threading.Thread] = None


class LinksPayload(BaseModel):
    account_url:  str
    post_urls:    list[str]
    full_name:    str
    email:        str
    country:      str
    work_type:    str
    rights_owner: str
    work_desc:    str
    inf_desc:     str
    signature:    str
    imap_user:    str = ""
    imap_pass:    str = ""


class ImapTestPayload(BaseModel):
    imap_user: str
    imap_pass: str


# ── helpers ──────────────────────────────────────────────────────────────────

def load_status() -> dict:
    if STATUS_FILE.exists():
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {"state": "idle", "total": 0, "done": 0, "failed": 0, "log": []}


def save_status(data: dict):
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def load_stats() -> dict:
    default = {
        "services": {
            "facebook": {
                "total_sent":    0,
                "total_success": 0,
                "total_failed":  0,
                "total_batches": 0,
                "sessions": [],      # last 20 sessions
            }
        }
    }
    if STATS_FILE.exists():
        with open(STATS_FILE) as f:
            return json.load(f)
    return default


def save_stats(data: dict):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_session(service: str, total: int, success: int, failed: int, batches: int):
    stats = load_stats()
    svc = stats["services"].setdefault(service, {
        "total_sent": 0, "total_success": 0,
        "total_failed": 0, "total_batches": 0, "sessions": [],
    })
    svc["total_sent"]    += total
    svc["total_success"] += success
    svc["total_failed"]  += failed
    svc["total_batches"] += batches
    svc["sessions"].append({
        "date":    datetime.now().strftime("%d.%m.%Y %H:%M"),
        "total":   total,
        "success": success,
        "failed":  failed,
        "batches": batches,
    })
    svc["sessions"] = svc["sessions"][-20:]   # keep last 20
    save_stats(stats)


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/start")
async def start_bot(payload: LinksPayload):
    global bot_worker, bot_thread

    if bot_thread and bot_thread.is_alive():
        return JSONResponse({"error": "Бот уже запущен"}, status_code=400)

    post_urls = [u.strip() for u in payload.post_urls if u.strip()]
    if not post_urls:
        return JSONResponse({"error": "Список ссылок пуст"}, status_code=400)

    static = {
        "full_name":         payload.full_name,
        "email":             payload.email,
        "country":           payload.country,
        "work_type":         payload.work_type,
        "rights_owner_name": payload.rights_owner,
        "work_description":  payload.work_desc,
        "infringement_desc": payload.inf_desc,
        "signature":         payload.signature,
        "imap_user":         payload.imap_user,
        "imap_pass":         payload.imap_pass,
    }

    batches = -(-len(post_urls) // 30)
    save_status({
        "state": "running", "total": len(post_urls),
        "done": 0, "failed": 0,
        "log": [f"Запуск: {len(post_urls)} постов, {batches} батчей..."],
    })

    bot_worker = BotWorker(
        account_url=payload.account_url.strip(),
        post_urls=post_urls,
        static=static,
        status_file=STATUS_FILE,
        on_finish=lambda done, failed, b: record_session(
            "facebook", len(post_urls), done, failed, b
        ),
    )

    bot_thread = threading.Thread(target=bot_worker.run, daemon=True)
    bot_thread.start()

    return {"status": "started", "total": len(post_urls)}


@app.post("/api/stop")
async def stop_bot():
    global bot_worker
    if bot_worker:
        bot_worker.stop()
        return {"status": "stopping"}
    return JSONResponse({"error": "Бот не запущен"}, status_code=400)


@app.get("/api/status")
async def get_status():
    return load_status()


@app.get("/api/stats")
async def get_stats():
    return load_stats()


@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    urls = [l for l in lines if l.startswith("http")]
    return {"urls": urls, "count": len(urls)}


@app.post("/api/reset")
async def reset():
    save_status({"state": "idle", "total": 0, "done": 0, "failed": 0, "log": []})
    return {"status": "reset"}


@app.get("/api/session-exists")
async def session_exists():
    return {"exists": Path("cookies/session.json").exists()}


@app.post("/api/test-imap")
async def test_imap(payload: ImapTestPayload):
    ok, msg = test_imap_connection(payload.imap_user, payload.imap_pass)
    return {"ok": ok, "message": msg}
