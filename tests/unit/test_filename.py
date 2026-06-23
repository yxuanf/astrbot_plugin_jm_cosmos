"""下载文件名生成器测试。"""

import importlib.util
import re
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[2] / "utils" / "filename.py"
_SPEC = importlib.util.spec_from_file_location("jm_cosmos_filename_utils", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
generate_album_filename = _MODULE.generate_album_filename
generate_sent_filename = _MODULE.generate_sent_filename


def test_telegram_metadata_filename():
    assert (
        generate_album_filename("123", title="测试本子", author="测试作者")
        == "测试本子-测试作者"
    )


def test_metadata_filename_sanitizes_invalid_characters_and_whitespace():
    name = generate_album_filename(
        "123",
        title='  测试/本子:*?\n第二行  ',
        author=' 作者<>|"名 ',
    )

    assert name == "测试_本子____第二行-作者____名"
    assert not re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', name)


def test_metadata_filename_uses_fallbacks():
    assert (
        generate_album_filename("456", title="", author="")
        == "JM456-未知作者"
    )


def test_metadata_filename_preserves_password_hint():
    assert (
        generate_album_filename(
            "123",
            password="secret",
            show_password=True,
            title="测试本子",
            author="测试作者",
        )
        == "测试本子-测试作者#PWsecret"
    )


def test_metadata_filename_is_utf8_byte_limited():
    name = generate_album_filename(
        "123",
        title="漫" * 200,
        author="作者" * 100,
    )

    assert len(name.encode("utf-8")) <= 220
    assert name.endswith("-" + "作者" * 13)


def test_legacy_filename_remains_id_and_timestamp(monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1700000000)

    assert generate_album_filename("123") == "123_1700000000"
    assert (
        generate_album_filename(
            "123",
            password="secret",
            chapter_idx=2,
            show_password=True,
        )
        == "123_Ch2_1700000000#PWsecret"
    )


def test_telegram_multi_part_filename_keeps_part_number_at_front():
    original = "今晚與莫娜無事生非" * 10 + "-なンとか_part2.zip"

    sent = generate_sent_filename(
        original,
        "telegram",
        part_index=2,
        total_parts=3,
    )

    assert sent.startswith("part2of3_")
    assert sent.endswith("-なンとか.zip")
    assert "_part2.zip" not in sent


def test_sent_filename_keeps_single_file_and_other_platforms_unchanged():
    single = "测试本子-测试作者.zip"
    part = "测试本子-测试作者_part1.zip"

    assert generate_sent_filename(single, "telegram") == single
    assert generate_sent_filename(part, "qq_official", 1, 3) == part
