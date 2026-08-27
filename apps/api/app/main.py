"""Phase 01: a local health endpoint, with no media or pipeline behavior."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


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
    allow_methods=["GET"],
    allow_headers=[],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "personal-ai-video-editor-api"}
