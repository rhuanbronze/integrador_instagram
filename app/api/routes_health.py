from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.database.session import check_database

router = APIRouter()


@router.get("/health")
def health(request: Request):
    try:
        check_database(request.app.state.engine)
    except Exception:
        return JSONResponse({"status": "error", "database": "unavailable"}, status_code=503)
    return {"status": "ok", "database": "ok"}
