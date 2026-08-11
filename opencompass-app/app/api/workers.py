"""Worker 池查询 / 健康检查。"""
import logging
import shutil

from fastapi import APIRouter, HTTPException

from app.models.request import CapacityAdjustRequest
from app.models.response import FreeWorkerCount, HealthCheck

log = logging.getLogger(__name__)

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
    from app.main import get_instance_state, get_state_store

    inst = get_instance_state()
    if not inst.ready:
        raise HTTPException(503, "Instance recovering after restart")

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


@router.patch("/me/capacity")
async def adjust_capacity(req: CapacityAdjustRequest) -> dict[str, int]:
    """调整并发上限（运维）。

    约束（PRD FR-3.3 / 7.2）：
      - max_concurrent > 0（Pydantic gt=0 自动校验 → 422）
      - max_concurrent >= running_count（业务校验 → 409）

    立即生效；不持久化（重启后从环境变量 MAX_CONCURRENT 读回）。
    """
    from app.main import get_instance_state

    inst = get_instance_state()
    if not inst.ready:
        raise HTTPException(503, "Instance recovering after restart")
    if req.max_concurrent < inst.running_count():
        raise HTTPException(
            409,
            f"New max ({req.max_concurrent}) less than current running "
            f"({inst.running_count()})",
        )
    inst.max_concurrent = req.max_concurrent
    log.info("Capacity adjusted to %d via PATCH /me/capacity", req.max_concurrent)
    return {"max_concurrent": inst.max_concurrent}
