"""Optional local-only manual stand; registration is controlled by application settings."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["development"])
PAGE_PATH = Path(__file__).resolve().parents[2] / "dev_stand" / "index.html"


@router.get("/dev", response_class=HTMLResponse, include_in_schema=False)
def dev_stand() -> HTMLResponse:
    return HTMLResponse(
        PAGE_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
