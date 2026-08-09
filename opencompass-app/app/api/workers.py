"""Worker 池查询 / 健康检查。"""
import shutil

from fastapi import APIRouter

from app.models.response import FreeWorkerCount, HealthCheck


router = APIRouter(prefix="/api/v1/workers", tags=["workers"])
health_router = APIRouter(tags=["health"])


@router.get("/me/free", response_model=FreeWorkerCount)
async def free_workers() -> FreeWorkerCount:
    # 延迟导入：避免与 app.main 的循环导入
    from app.main import get_instance_state

    s = get_instance_state()
    return FreeWorkerCount(
        available=s.available_slots(),
        max=s.max_concurrent,
        running=s.running_count(),
    )


@health_router.get("/health", response_model=HealthCheck)
async def health() -> HealthCheck:
    # 延迟导入：避免与 app.main 的循环导入
    from app.main import get_state_store

    checks: dict[str, str] = {}
    try:
        get_state_store().list_ids()
        checks["nfs_state"] = "ok"
    except Exception as e:
        checks["nfs_state"] = f"fail: {e}"

    checks["opencompass_binary"] = (
        "ok" if shutil.which("opencompass") else "missing"
    )
    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthCheck(status=overall, checks=checks)
