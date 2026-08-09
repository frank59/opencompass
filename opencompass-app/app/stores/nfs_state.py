"""NFS JSON 任务状态持久化。

设计要点：
- 任意实例可读（GET /jobs/{id}）。
- 写者独占（POST /jobs 成功后由创建实例独占）。
- 原子写：tempfile.mkstemp + fsync + os.replace（NFS 友好）。
"""
import json
import os
import tempfile
from pathlib import Path


class JobStateStore:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.json"

    def write_atomic(self, job_id: str, payload: dict) -> None:
        """原子写：临时文件 → fsync → os.replace（NFS 上保证可见性）。"""
        target = self._path(job_id)
        fd, tmp = tempfile.mkstemp(
            dir=self.base_dir, prefix=f".{job_id}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def read(self, job_id: str) -> dict | None:
        try:
            with open(self._path(job_id), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def exists(self, job_id: str) -> bool:
        return self._path(job_id).exists()

    def list_ids(self) -> list[str]:
        """列出所有 job_id；排除以点号开头（tmp 文件）。"""
        ids = []
        for p in self.base_dir.iterdir():
            if p.name.startswith("."):
                continue
            if p.suffix == ".json":
                ids.append(p.stem)
        return ids
