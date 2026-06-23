"""下载文件名生成器。"""

import re
import time


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WHITESPACE = re.compile(r"\s+")
_MAX_TELEGRAM_BASENAME_BYTES = 220


def _sanitize_filename_component(value: str, fallback: str) -> str:
    """清理 Windows/Linux 文件系统及 Telegram 不宜使用的字符。"""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", str(value or ""))
    cleaned = _WHITESPACE.sub(" ", cleaned).strip(" .")
    return cleaned or fallback


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """按 UTF-8 字节安全截断，避免切断中文或 Emoji。"""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(" .")


def _generate_metadata_filename(
    album_id: str,
    title: str,
    author: str,
    password: str,
    show_password: bool,
) -> str:
    """生成 Telegram 使用的“本子名-作者”文件名。"""
    safe_title = _sanitize_filename_component(title, f"JM{album_id}")
    safe_author = _sanitize_filename_component(author, "未知作者")

    password_hint = ""
    if show_password and password:
        safe_password = _sanitize_filename_component(password, "")
        if safe_password:
            password_hint = f"#PW{safe_password}"

    # 为扩展名和 _partN 后缀预留空间。异常超长的密码提示不写入文件名，
    # 但不会改变 packer 实际使用的加密密码。
    if len(password_hint.encode("utf-8")) >= _MAX_TELEGRAM_BASENAME_BYTES // 2:
        password_hint = ""

    metadata_budget = _MAX_TELEGRAM_BASENAME_BYTES - len(
        password_hint.encode("utf-8")
    )
    author_budget = min(80, len(safe_author.encode("utf-8")))
    safe_author = _truncate_utf8(safe_author, author_budget) or "未知作者"
    title_budget = max(
        1, metadata_budget - len(safe_author.encode("utf-8")) - len("-".encode())
    )
    safe_title = _truncate_utf8(safe_title, title_budget) or f"JM{album_id}"

    return f"{safe_title}-{safe_author}{password_hint}"


def generate_album_filename(
    album_id: str,
    password: str = "",
    chapter_idx: int | None = None,
    show_password: bool = False,
    title: str | None = None,
    author: str | None = None,
) -> str:
    """
    生成下载文件名

    Args:
        album_id: 本子ID
        password: 打包密码
        chapter_idx: 章节序号 (仅章节下载时传入)
        show_password: 是否显示密码提示
        title: 本子标题；传入时启用“本子名-作者”命名
        author: 本子作者；元数据命名时为空则使用“未知作者”

    Returns:
        生成的文件名 (不含扩展名)
    """
    if title is not None:
        return _generate_metadata_filename(
            album_id=album_id,
            title=title,
            author=author or "",
            password=password,
            show_password=show_password,
        )

    timestamp = int(time.time())

    # 基础格式: ID_timestamp 或 ID_chN_timestamp
    if chapter_idx is not None:
        name = f"{album_id}_Ch{chapter_idx}_{timestamp}"
    else:
        name = f"{album_id}_{timestamp}"

    # 可选：添加密码提示
    if show_password and password:
        name += f"#PW{password}"

    return name
