"""平台发送兼容辅助函数。"""

from __future__ import annotations

from typing import Any


def get_platform_file_size_limit_mb(
    platform_name: str, qq_limit_mb: int, telegram_limit_mb: int
) -> int:
    """返回指定平台的基础打包分卷阈值，0 表示不分卷。"""
    if platform_name == "qq_official":
        return max(0, int(qq_limit_mb))
    if platform_name == "telegram":
        return max(0, int(telegram_limit_mb))
    return 0


def configure_telegram_upload_timeout(client: Any, timeout_seconds: int) -> bool:
    """调整 python-telegram-bot 的媒体上传超时。

    ``ExtBot._request`` 是 ``(get_updates_request, api_request)`` 二元组；
    文件上传由索引 1 的普通 API 请求器执行。媒体请求的 write timeout 又由
    ``HTTPXRequest._media_write_timeout`` 单独控制，不能只修改 HTTPX client。

    Returns:
        成功识别并更新请求器时返回 True，否则返回 False。
    """
    timeout = max(1, int(timeout_seconds))
    requests = getattr(client, "_request", None)
    if not isinstance(requests, (tuple, list)) or len(requests) < 2:
        return False

    request = requests[1]
    if request is None or not hasattr(request, "_media_write_timeout"):
        return False

    request._media_write_timeout = float(timeout)

    http_client = getattr(request, "_client", None)
    current = getattr(http_client, "timeout", None)
    if http_client is not None and current is not None:
        try:
            import httpx

            connect = max(10.0, float(current.connect or 0))
            pool = max(10.0, float(current.pool or 0))
            http_client.timeout = httpx.Timeout(
                connect=connect,
                read=float(timeout),
                write=float(timeout),
                pool=pool,
            )
        except (ImportError, TypeError, ValueError, AttributeError):
            # _media_write_timeout 已经是文件上传真正使用的关键值；
            # 底层 HTTPX 默认值无法同步时仍视为配置成功。
            pass

    return True
