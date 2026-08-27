"""Local health and Phase 02 media APIs; no editing pipeline."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.media import router, MediaError


app = FastAPI(
    title="Personal AI Video Editor API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Media-Import"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "personal-ai-video-editor-api"}


@app.exception_handler(MediaError)
async def media_error(request, error: MediaError):
    return JSONResponse(status_code=error.status, content={"error": error.result()})


app.include_router(router)
