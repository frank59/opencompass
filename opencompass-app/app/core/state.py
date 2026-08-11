"""Worker 池状态（in-memory）。

设计要点：
- read path 无锁（O(1) count/contains）
- acquire/release 走 asyncio.Lock（write path 互斥）
- 进程对象由 track_process 保存，wait_and_finalize 用

NOTE: get_process 是同步只读访问（CPython list/dict GIL 保护下安全）。
"""
import asyncio
from typing import Any


class InstanceState:
    def __init__(self, max_concurrent: int, instance_id: str):
        self.max_concurrent = max_concurrent
        self.instance_id = instance_id
        self.ready: bool = False
        self._running: set[str] = set()
        self._processes: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ----- read paths (lock-free) -----
    def running_count(self) -> int:
        return len(self._running)

    def available_slots(self) -> int:
        return max(0, self.max_concurrent - len(self._running))

    def is_at_capacity(self) -> bool:
        return len(self._running) >= self.max_concurrent

    def get_process(self, job_id: str) -> Any | None:
        return self._processes.get(job_id)

    # ----- write paths (locked) -----
    async def try_acquire(self, job_id: str) -> bool:
        async with self._lock:
            if self.is_at_capacity():
                return False
            self._running.add(job_id)
            return True

    async def release(self, job_id: str) -> None:
        async with self._lock:
            self._running.discard(job_id)
            self._processes.pop(job_id, None)

    def track_process(self, job_id: str, proc: Any) -> None:
        """保存进程对象引用（不参与锁保护，调用方负责时序）。"""
        self._processes[job_id] = proc

    # ----- lifecycle / recovery helpers (Phase 3) -----
    def mark_ready(self) -> None:
        """设置 ready=True（幂等）。由 lifespan recover 完成后调用。"""
        self.ready = True

    def reserve_for_recovery(self, job_id: str) -> None:
        """recover 时占位（同步，单线程上下文安全）。

        行为：将 job_id 加入 _running（不持锁，不参与并发限流判断路径）。

        约束：仅可在 lifespan startup 单线程上下文中调用；调用方需紧接
        release(job_id) 完成 slot 计数清零。
        """
        self._running.add(job_id)


def get_instance_state() -> "InstanceState":
    """占位实现。真正实现在 app/main.py（lifespan 内全局单例）。"""
    raise RuntimeError("get_instance_state must be called via FastAPI lifespan")
