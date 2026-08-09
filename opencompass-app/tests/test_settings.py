from app.core.settings import Settings


def test_settings_defaults_to_8_concurrent(monkeypatch):
    monkeypatch.delenv("MAX_CONCURRENT", raising=False)
    s = Settings()
    assert s.max_concurrent == 8


def test_settings_reads_max_concurrent_env(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT", "16")
    s = Settings()
    assert s.max_concurrent == 16


def test_settings_reads_oc_data_root(monkeypatch):
    monkeypatch.setenv("OC_DATA_ROOT", "/tmp/oc-data")
    s = Settings()
    assert s.oc_data_root == "/tmp/oc-data"


def test_instance_id_falls_back_to_hostname(monkeypatch):
    monkeypatch.delenv("INSTANCE_ID", raising=False)
    s = Settings()
    # INSTANCE_ID 为空字符串时回退
    assert s.instance_id != ""
    assert ":" in s.instance_id or len(s.instance_id) > 0


def test_get_settings_returns_singleton():
    from app.core.settings import get_settings
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
