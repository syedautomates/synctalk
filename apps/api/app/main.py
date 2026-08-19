from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging
from app.request_logging import RequestLoggingMiddleware
from app.routes import auth, internal, jobs, looks, metrics, profiles, videos
from app.services.storage import ensure_bucket_exists, ensure_lifecycle_policy

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bucket_exists()
    ensure_lifecycle_policy()
    yield


app = FastAPI(title="SyncTalk API", lifespan=lifespan)

# Starlette's add_middleware() prepends, so middleware added later ends up OUTER (see
# Starlette's build_middleware_stack) -- CORSMiddleware, added after this one, therefore
# wraps it. That's fine here: CORS only intercepts OPTIONS preflights (which we don't
# want structured-logged as real requests anyway) and otherwise just adds response
# headers around whatever this middleware and the route handler already produced, so
# request_id is still bound in the contextvar before any route code runs either way.
app.add_middleware(RequestLoggingMiddleware)

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
app.include_router(metrics.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
