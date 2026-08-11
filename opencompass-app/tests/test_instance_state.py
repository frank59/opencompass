import asyncio

import pytest

from app.core.state import InstanceState


@pytest.fixture
def inst():
    return InstanceState(max_concurrent=3, instance_id="test-inst")


def test_is_at_capacity_false_when_empty(inst):
    assert not inst.is_at_capacity()
    assert inst.running_count() == 0
    assert inst.available_slots() == 3


def test_available_slots_clamps_to_zero(inst):
    s = InstanceState(max_concurrent=2, instance_id="x")
    assert s.available_slots() == 2
    s._running.add("a")  # 手动注入测试边界
    s._running.add("b")
    assert s.available_slots() == 0


def test_try_acquire_returns_true_when_room(inst):
    assert asyncio.run(inst.try_acquire("job_a")) is True
    assert inst.running_count() == 1


def test_try_acquire_returns_false_when_full(inst):
    asyncio.run(inst.try_acquire("a"))
    asyncio.run(inst.try_acquire("b"))
    asyncio.run(inst.try_acquire("c"))
    assert inst.is_at_capacity()
    assert asyncio.run(inst.try_acquire("d")) is False


def test_release_idempotent(inst):
    asyncio.run(inst.try_acquire("job_a"))
    asyncio.run(inst.release("job_a"))
    # 重复 release 不报错
    asyncio.run(inst.release("job_a"))
    assert inst.running_count() == 0


def test_track_process_stores_proc(inst):
    sentinel = object()
    inst.track_process("job_a", sentinel)
    assert inst.get_process("job_a") is sentinel
    assert inst.get_process("nope") is None


def test_concurrent_acquire_respects_limit(inst):
    """N+M 并发 acquire 中，最多 3 个成功（M 实例 max=3）。"""
    inst2 = InstanceState(max_concurrent=3, instance_id="c")
    results = []

    async def worker(idx: int):
        ok = await inst2.try_acquire(f"job_{idx}")
        results.append(ok)

    async def run_all():
        await asyncio.gather(*(worker(i) for i in range(10)))

    asyncio.run(run_all())
    assert sum(results) == 3


def test_instance_id_exposed(inst):
    assert inst.instance_id == "test-inst"


def test_ready_default_false(inst):
    assert inst.ready is False


def test_mark_ready_sets_true(inst):
    inst.mark_ready()
    assert inst.ready is True


def test_mark_ready_idempotent(inst):
    inst.mark_ready()
    inst.mark_ready()
    assert inst.ready is True


def test_reserve_for_recovery_aligns_running_count(inst):
    inst.reserve_for_recovery("job_a")
    assert inst.running_count() == 1
    asyncio.run(inst.release("job_a"))
    assert inst.running_count() == 0
