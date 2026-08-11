"""单元测试 app.utils.recovery。"""
import os

import pytest

from app.utils.recovery import is_pid_in_current_session


def test_is_pid_returns_true_for_self():
    """当前进程 PID 必然存活。"""
    assert is_pid_in_current_session(os.getpid()) is True


def test_is_pid_returns_false_for_missing():
    """PID 999999 几乎肯定不存在。"""
    assert is_pid_in_current_session(999999) is False


def test_is_pid_returns_false_for_none():
    assert is_pid_in_current_session(None) is False
