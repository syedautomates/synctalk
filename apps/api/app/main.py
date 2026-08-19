from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import auth, internal, jobs, looks, profiles, videos
from app.services.storage import ensure_bucket_exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bucket_exists()
    yield


app = FastAPI(title="SyncTalk API", lifespan=lifespan)

# Single-user dev tool — the Next.js wizard (M6) runs on a different origin/port than
# this API, so the browser needs CORS headers for its fetch() calls to succeed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(looks.router)
app.include_router(jobs.router)
app.include_router(internal.router)
app.include_router(videos.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
