"""平台发送兼容辅助函数测试。"""

import sys
import importlib.util
from pathlib import Path
from types import SimpleNamespace


_MODULE_PATH = Path(__file__).resolve().parents[2] / "utils" / "platform.py"
_SPEC = importlib.util.spec_from_file_location("jm_cosmos_platform_utils", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
configure_telegram_upload_timeout = _MODULE.configure_telegram_upload_timeout
get_platform_file_size_limit_mb = _MODULE.get_platform_file_size_limit_mb


def _request():
    return SimpleNamespace(
        _media_write_timeout=20.0,
        _client=SimpleNamespace(
            timeout=SimpleNamespace(connect=5.0, read=5.0, write=5.0, pool=1.0)
        ),
    )


def test_configures_api_request_from_request_tuple(monkeypatch):
    class FakeTimeout:
        def __init__(self, *, connect, read, write, pool):
            self.connect = connect
            self.read = read
            self.write = write
            self.pool = pool

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Timeout=FakeTimeout))
    updates_request = _request()
    api_request = _request()
    client = SimpleNamespace(_request=(updates_request, api_request))

    assert configure_telegram_upload_timeout(client, 180) is True
    assert updates_request._media_write_timeout == 20.0
    assert api_request._media_write_timeout == 180.0
    assert api_request._client.timeout.write == 180.0
    assert api_request._client.timeout.read == 180.0
    assert api_request._client.timeout.connect == 10.0
    assert api_request._client.timeout.pool == 10.0


def test_rejects_unknown_request_layout_without_mutation():
    request = _request()
    client = SimpleNamespace(_request=request)

    assert configure_telegram_upload_timeout(client, 180) is False
    assert request._media_write_timeout == 20.0


def test_selects_platform_file_size_limit():
    assert get_platform_file_size_limit_mb("telegram", 5, 8) == 8
    assert get_platform_file_size_limit_mb("qq_official", 5, 8) == 5
    assert get_platform_file_size_limit_mb("aiocqhttp", 5, 8) == 0


def test_platform_file_size_limit_zero_disables_split():
    assert get_platform_file_size_limit_mb("telegram", 5, 0) == 0
    assert get_platform_file_size_limit_mb("qq_official", 0, 5) == 0
