"""Phase 4: 任务日志端点 GET /api/v1/jobs/{id}/log 测试。

覆盖：
- _read_log_window helper：行边界、tail、start_line 越界、空文件、不完整最后行、UTF-8 容错
- 端点：200 + content + tail=true + limit 越界 + 404 + stale state（无 log_path）
"""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.jobs import _read_log_window
from app.core.dataset_registry import DatasetRegistry
from app.core.dataset_whitelist import DatasetWhitelist
from app.core.model_whitelist import ModelWhitelist
from app.main import create_app

# -------------------- helper 单元测试 --------------------

def test_read_log_window_missing_file(tmp_path):
    """日志文件不存在 → 返回空 + eof=True。"""
    log_path = tmp_path / "nope.log"
    lines, total, start, eof = _read_log_window(log_path, 0, 10, False)
    assert lines == []
    assert total == 0
    assert eof is True


def test_read_log_window_empty_file(tmp_path):
    log_path = tmp_path / "empty.log"
    log_path.write_bytes(b"")
    lines, total, _, eof = _read_log_window(log_path, 0, 10, False)
    assert lines == []
    assert total == 0
    assert eof is True


def test_read_log_window_basic(tmp_path):
    log_path = tmp_path / "a.log"
    log_path.write_bytes(b"line1\nline2\nline3\n")
    lines, total, start, eof = _read_log_window(log_path, 0, 10, False)
    assert lines == ["line1", "line2", "line3"]
    assert total == 3
    assert start == 0
    assert eof is True


def test_read_log_window_incomplete_last_line(tmp_path):
    """文件末尾没有 \\n 的最后一行也算 1 行。"""
    log_path = tmp_path / "a.log"
    log_path.write_bytes(b"line1\nline2\nline3")  # no trailing newline
    lines, total, _, eof = _read_log_window(log_path, 0, 10, False)
    assert lines == ["line1", "line2", "line3"]
    assert total == 3
    assert eof is True


def test_read_log_window_pagination(tmp_path):
    log_path = tmp_path / "a.log"
    log_path.write_bytes(("\n".join(f"line{i}" for i in range(100)) + "\n").encode())
    lines, total, start, eof = _read_log_window(log_path, 50, 20, False)
    assert total == 100
    assert start == 50
    assert len(lines) == 20
    assert lines[0] == "line50"
    assert lines[-1] == "line69"
    assert eof is False  # 还剩 30 行


def test_read_log_window_start_line_clamps_to_zero(tmp_path):
    """start_line 负数（Query ge=0 已挡，但 helper 也安全）→ 从 0 开始。"""
    log_path = tmp_path / "a.log"
    log_path.write_bytes(b"a\nb\nc\n")
    lines, total, start, _ = _read_log_window(log_path, -5, 10, False)
    assert start == 0
    assert lines == ["a", "b", "c"]


def test_read_log_window_start_line_beyond_eof(tmp_path):
    """start_line 越界 → 返回空 + eof=True。"""
    log_path = tmp_path / "a.log"
    log_path.write_bytes(b"a\nb\n")
    lines, total, start, eof = _read_log_window(log_path, 100, 10, False)
    assert lines == []
    assert total == 2
    assert start == 2  # 截断到 total
    assert eof is True


def test_read_log_window_tail_ignores_start_line(tmp_path):
    log_path = tmp_path / "a.log"
    log_path.write_bytes(("\n".join(f"L{i}" for i in range(50)) + "\n").encode())
    lines, total, start, eof = _read_log_window(log_path, 999, 5, True)
    assert total == 50
    assert start == 45  # 50 - 5
    assert lines == ["L45", "L46", "L47", "L48", "L49"]
    assert eof is True


def test_read_log_window_tail_more_than_total(tmp_path):
    """limit 大于总行数时 tail 返回全部。"""
    log_path = tmp_path / "a.log"
    log_path.write_bytes(b"a\nb\nc\n")
    lines, total, start, eof = _read_log_window(log_path, 0, 100, True)
    assert lines == ["a", "b", "c"]
    assert total == 3
    assert start == 0
    assert eof is True


def test_read_log_window_utf8_replace_on_decode_error(tmp_path):
    """含非 UTF-8 字节 → 用 U+FFFD 替换，不抛错。"""
    log_path = tmp_path / "a.log"
    log_path.write_bytes(b"ok\n\xff\xfe broken\n")
    lines, _, _, _ = _read_log_window(log_path, 0, 10, False)
    assert lines[0] == "ok"
    assert "\ufffd" in lines[1]


# -------------------- 端点集成测试 --------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    """复用 test_jobs_api.py 的模式：mock 白名单 + mock subprocess_runner。"""
    fake_yaml = tmp_path / "di.yaml"
    fake_yaml.write_text(
        "- gsm8k:\n    configpath: opencompass/configs/datasets/gsm8k/gsm8k_gen.py\n",
        encoding="utf-8",
    )
    DatasetRegistry._INDEX = DatasetRegistry._load_with_path(fake_yaml)

    monkeypatch.setattr(
        ModelWhitelist, "_TYPES",
        frozenset({"opencompass.models.openai_api.OpenAISDK"}),
    )
    monkeypatch.setattr(
        DatasetWhitelist, "_DATASET",
        frozenset({"opencompass.datasets.custom.CustomDataset"}),
    )
    monkeypatch.setattr(DatasetWhitelist, "_EVAL", frozenset({"AccEvaluator"}))
    monkeypatch.setattr(DatasetWhitelist, "_INFER", frozenset({"GenInferencer"}))
    monkeypatch.setattr(DatasetWhitelist, "_RETRIEVER", frozenset({"ZeroRetriever"}))
    monkeypatch.setattr(DatasetWhitelist, "_PROMPT", frozenset({"PromptTemplate"}))

    import app.executor.subprocess_runner as sr

    async def fake_start(job_id, config_path, log_path=None):
        proc = AsyncMock()
        proc.pid = 88888
        proc.wait = AsyncMock(return_value=0)
        # 模拟 log_path 给定时挂 _log_fp
        if log_path is not None:
            proc._log_fp = None
        return proc

    async def fake_wait_and_finalize(*args, **kwargs):
        pass

    monkeypatch.setattr(sr, "start", fake_start)
    monkeypatch.setattr(sr, "wait_and_finalize", fake_wait_and_finalize)

    app = create_app()
    with TestClient(app) as c:
        yield c

    DatasetRegistry._INDEX = None


def _create_job(client, job_id: str) -> None:
    """POST /api/v1/jobs 创建任务，state 写入 store。"""
    req = {
        "job_id": job_id,
        "datasets": [{"abbr": "gsm8k"}],
        "models": [{
            "type": "opencompass.models.openai_api.OpenAISDK",
            "path": "qwen", "key": "sk-test",
        }],
    }
    res = client.post("/api/v1/jobs", json=req)
    assert res.status_code == 201, res.text


def _write_log(state, content: bytes) -> str:
    """根据 state 里的 log_path 写日志，返回实际路径。"""
    from app.main import get_state_store

    store = get_state_store()
    s = store.read(state["job_id"])
    log_path = s["log_path"]
    import os
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "wb") as f:
        f.write(content)
    return log_path


def test_log_endpoint_200_after_create_returns_empty_when_no_log_file(client):
    """job 创建后 log 文件未生成 → 200 + 空 lines + eof=true。"""
    _create_job(client, "job_log_empty")
    res = client.get("/api/v1/jobs/job_log_empty/log")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["job_id"] == "job_log_empty"
    assert body["total_lines"] == 0
    assert body["returned_lines"] == 0
    assert body["lines"] == []
    assert body["eof"] is True
    assert body["log_path"].endswith("opencompass.log")


def test_log_endpoint_returns_paginated_lines(client):
    _create_job(client, "job_log_page")
    state = {"job_id": "job_log_page"}
    _write_log(state, ("\n".join(f"line{i}" for i in range(100)) + "\n").encode())

    # 第一页
    res = client.get("/api/v1/jobs/job_log_page/log?start_line=0&limit=10")
    assert res.status_code == 200
    body = res.json()
    assert body["total_lines"] == 100
    assert body["start_line"] == 0
    assert body["returned_lines"] == 10
    assert body["lines"][0] == "line0"
    assert body["lines"][-1] == "line9"
    assert body["eof"] is False

    # 第二页
    res2 = client.get("/api/v1/jobs/job_log_page/log?start_line=10&limit=10")
    body2 = res2.json()
    assert body2["start_line"] == 10
    assert body2["lines"][0] == "line10"
    assert body2["lines"][-1] == "line19"

    # 末页
    res3 = client.get("/api/v1/jobs/job_log_page/log?start_line=95&limit=10")
    body3 = res3.json()
    assert body3["start_line"] == 95
    assert body3["returned_lines"] == 5
    assert body3["eof"] is True


def test_log_endpoint_tail_returns_last_n_lines(client):
    _create_job(client, "job_log_tail")
    state = {"job_id": "job_log_tail"}
    _write_log(state, ("\n".join(f"L{i}" for i in range(20)) + "\n").encode())

    res = client.get("/api/v1/jobs/job_log_tail/log?tail=true&limit=5")
    assert res.status_code == 200
    body = res.json()
    assert body["start_line"] == 15  # 20 - 5
    assert body["returned_lines"] == 5
    assert body["lines"] == ["L15", "L16", "L17", "L18", "L19"]
    assert body["eof"] is True


def test_log_endpoint_404_when_job_not_found(client):
    res = client.get("/api/v1/jobs/no_such_job_xyz/log")
    assert res.status_code == 404


def test_log_endpoint_limit_out_of_range_rejected(client):
    """limit > 1000 → 422（FastAPI Query validation）。"""
    _create_job(client, "job_log_lim")
    res = client.get("/api/v1/jobs/job_log_lim/log?limit=99999")
    assert res.status_code == 422


def test_log_endpoint_start_line_negative_rejected(client):
    _create_job(client, "job_log_neg")
    res = client.get("/api/v1/jobs/job_log_neg/log?start_line=-1")
    assert res.status_code == 422


def test_log_endpoint_handles_stale_state_without_log_path(client, monkeypatch, tmp_path):
    """老实例 / 旧版本 state 没有 log_path 字段 → 200 + 空 content。"""
    _create_job(client, "job_stale")
    # 把 log_path 字段从 state 里抹掉
    from app.main import get_state_store
    store = get_state_store()
    s = store.read("job_stale")
    s.pop("log_path", None)
    store.write_atomic("job_stale", s)

    res = client.get("/api/v1/jobs/job_stale/log")
    assert res.status_code == 200
    body = res.json()
    assert body["log_path"] == ""
    assert body["lines"] == []
    assert body["total_lines"] == 0


def test_log_endpoint_includes_log_path_in_job_response(client):
    """POST /jobs 后 GET /jobs/{id} 应包含 log_path 字段（Phase 4）。"""
    _create_job(client, "job_with_logpath")
    res = client.get("/api/v1/jobs/job_with_logpath")
    assert res.status_code == 200
    body = res.json()
    assert "log_path" in body
    assert body["log_path"].endswith("/logs/opencompass.log")
    assert "/_in_progress/job_with_logpath/" in body["log_path"]