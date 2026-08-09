"""FastAPI 入口。"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.api.workers import router as workers_router, health_router
from app.core.settings import Settings
from app.core.state import InstanceState
from app.stores.nfs_state import JobStateStore


state_store: JobStateStore | None = None
instance_state: InstanceState | None = None


def get_state_store() -> JobStateStore:
    if state_store is None:
        raise RuntimeError("state_store not initialized; check lifespan")
    return state_store


def get_instance_state() -> InstanceState:
    if instance_state is None:
        raise RuntimeError("instance_state not initialized; check lifespan")
    return instance_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state_store, instance_state
    s = Settings()
    base_dir = Path(s.oc_data_root) / "workspace" / "state" / "jobs"
    state_store = JobStateStore(base_dir=str(base_dir))
    instance_state = InstanceState(
        max_concurrent=s.max_concurrent,
        instance_id=s.instance_id,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="opencompass-app", lifespan=lifespan)
    app.include_router(workers_router)
    app.include_router(health_router)
    app.include_router(jobs_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        reload=False,
    )
