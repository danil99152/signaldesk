"""Веб-дашборд SignalDesk (FastAPI)."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ConfigError, load_settings, read_config_file, write_config_file
from .pipeline import STAGES, PipelineError, list_reports, load_report, reports_dir, run_analysis
from .sources import DEFAULT_FEEDS

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    market: str = Field("all", pattern="^(all|global|russia)$")
    hours: int | None = Field(None, ge=1, le=168)
    max_articles: int | None = Field(None, ge=4, le=80)


class SettingsUpdate(BaseModel):
    lookback_hours: int = Field(24, ge=1, le=168)
    max_articles: int = Field(25, ge=4, le=80)
    watchlist_global: list[str] = []
    watchlist_russia: list[str] = []
    telegram_channels: list[str] = []
    disabled_feeds: list[str] = []


class JobState:
    def __init__(self) -> None:
        self.running = False
        self.market = "all"
        self.stage = 0
        self.message = ""
        self.log: list[str] = []
        self.error: str | None = None
        self.report_id: str | None = None
        self.started_at: str | None = None
        self.task: asyncio.Task | None = None

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "market": self.market,
            "stage": self.stage,
            "stages": STAGES,
            "message": self.message,
            "log": self.log[-20:],
            "error": self.error,
            "report_id": self.report_id,
            "started_at": self.started_at,
        }


def _clean_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def create_app() -> FastAPI:
    job = JobState()

    def progress(stage: int, text: str) -> None:
        job.stage, job.message = stage, text
        job.log.append(f"{datetime.now():%H:%M:%S} {text}")

    async def worker(req: RunRequest) -> None:
        try:
            settings = load_settings(require_key=False)
            if req.hours:
                settings.lookback_hours = req.hours
            if req.max_articles:
                settings.max_articles = req.max_articles
            report = await run_analysis(settings, req.market, progress)
            job.report_id = report["id"]
            job.log.append(f"{datetime.now():%H:%M:%S} Готово")
        except (ConfigError, PipelineError) as exc:
            job.error = str(exc)
        except Exception as exc:  # показываем любую ошибку в интерфейсе
            log.exception("Анализ завершился ошибкой")
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.running = False

    def start(req: RunRequest) -> None:
        job.__init__()
        job.running, job.market = True, req.market
        job.started_at = datetime.now().isoformat(timespec="seconds")
        job.task = asyncio.create_task(worker(req))

    async def scheduler(hours: float) -> None:
        while True:
            await asyncio.sleep(hours * 3600)
            if not job.running:
                log.info("Плановый запуск анализа")
                start(RunRequest())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hours = float(os.getenv("AUTO_RUN_HOURS") or 0)
        task = asyncio.create_task(scheduler(hours)) if hours > 0 else None
        if task:
            log.info("Авто-запуск каждые %s ч", hours)
        yield
        for t in (task, job.task):
            if t:
                t.cancel()

    app = FastAPI(title="SignalDesk", docs_url="/api/docs", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    async def status() -> dict:
        settings = load_settings(require_key=False)
        return {
            "job": job.as_dict(),
            "api_key_set": bool(settings.api_key),
            "auto_run_hours": float(os.getenv("AUTO_RUN_HOURS") or 0),
        }

    @app.post("/api/run")
    async def run(req: RunRequest) -> dict:
        if job.running:
            raise HTTPException(409, "Анализ уже выполняется")
        start(req)
        return job.as_dict()

    @app.get("/api/reports")
    async def reports() -> list[dict]:
        return list_reports()

    @app.get("/api/reports/{report_id}")
    async def report(report_id: str) -> dict:
        data = load_report(report_id)
        if not data:
            raise HTTPException(404, "Отчёт не найден")
        return data

    @app.get("/api/reports/{report_id}/markdown")
    async def report_markdown(report_id: str) -> PlainTextResponse:
        if load_report(report_id) is None:
            raise HTTPException(404, "Отчёт не найден")
        path = reports_dir() / f"{report_id}.md"
        return PlainTextResponse(
            path.read_text(encoding="utf-8") if path.exists() else "",
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="signaldesk_{report_id}.md"'},
        )

    @app.delete("/api/reports/{report_id}")
    async def delete_report(report_id: str) -> dict:
        if load_report(report_id) is None:
            raise HTTPException(404, "Отчёт не найден")
        for ext in ("json", "md"):
            (reports_dir() / f"{report_id}.{ext}").unlink(missing_ok=True)
        return {"deleted": report_id}

    @app.get("/api/settings")
    async def get_settings() -> dict:
        s = load_settings(require_key=False)
        return {
            "lookback_hours": s.lookback_hours,
            "max_articles": s.max_articles,
            "watchlist_global": s.watchlist_global,
            "watchlist_russia": s.watchlist_russia,
            "telegram_channels": s.telegram_channels,
            "disabled_feeds": s.disabled_feeds,
            "feeds": [{"name": f.name, "url": f.url, "region": f.region} for f in DEFAULT_FEEDS],
            "fast_model": s.fast_model,
            "reasoning_model": s.reasoning_model,
            "api_key_set": bool(s.api_key),
        }

    @app.put("/api/settings")
    async def put_settings(update: SettingsUpdate) -> dict:
        data = read_config_file()
        data.update(
            {
                "lookback_hours": update.lookback_hours,
                "max_articles": update.max_articles,
                "watchlist": {
                    "global": _clean_list([t.upper() for t in update.watchlist_global]),
                    "russia": _clean_list([t.upper() for t in update.watchlist_russia]),
                },
                "telegram_channels": _clean_list(update.telegram_channels),
                "disabled_feeds": _clean_list(update.disabled_feeds),
            }
        )
        write_config_file(data)
        return await get_settings()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
