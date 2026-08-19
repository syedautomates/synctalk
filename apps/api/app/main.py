from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import auth, internal, jobs, looks, profiles
from app.services.storage import ensure_bucket_exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bucket_exists()
    yield


app = FastAPI(title="SyncTalk API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(looks.router)
app.include_router(jobs.router)
app.include_router(internal.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
