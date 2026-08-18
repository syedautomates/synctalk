from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import auth, profiles
from app.services.storage import ensure_bucket_exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bucket_exists()
    yield


app = FastAPI(title="SyncTalk API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(profiles.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
