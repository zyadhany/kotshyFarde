"""
app/main.py
───────────
FastAPI application entry point for the Kotchy ICPC Student Tracking System.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure project root is in sys.path for direct invocation
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.api import assignments, pages, students, tasks, users
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ensure database tables are created at application startup."""
    init_db()
    yield


app = FastAPI(
    title="Kotchy ICPC Tracker API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS Middleware ───────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount Static Files ────────────────────────────────────────
_STATIC_DIR = _PROJECT_ROOT / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# ── Register Frontend & API Routers ───────────────────────────
app.include_router(pages.router)
app.include_router(users.router)
app.include_router(students.router)
app.include_router(tasks.router)
app.include_router(assignments.router)


# ── Health Check ──────────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health_check() -> dict:
    """Service health probe."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
