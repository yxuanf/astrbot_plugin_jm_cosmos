"""
JMComic 打包模块 - 支持加密ZIP和PDF
"""

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from astrbot.api import logger

try:
    import pyzipper

    PYZIPPER_AVAILABLE = True
except ImportError:
    PYZIPPER_AVAILABLE = False

try:
    import fitz  # pymupdf

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# 长图打包参数
_LONG_IMG_WIDTH = 1200  # 统一宽度，所有图片缩放到此宽度后纵向拼接
_LONG_IMG_MAX_STRIP_HEIGHT = 12000  # 单段长图最大高度，超出则分段
_LONG_IMG_MAX_PER_STRIP = 30  # 单段长图最多包含的图片数
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _collect_images_sorted(source_dir: Path) -> list[Path]:
    """递归收集图片并按“自然顺序”排序。

    多章节本子按 Bd/Aid/Pindex 落盘，章节目录是 1、2、…、10、…、241。普通
    字符串排序会得到 1,10,11,…,2,20 的错误顺序；这里把路径中的数字段按整数比较，
    保证按 (章节, 页码) 的真实阅读顺序排列，PDF / 长图才不会乱序。
    """

    def natural_key(path: Path):
        rel = str(path.relative_to(source_dir))
        # 数字段按整数比较、其余按小写字符串比较；用 (类型标记, 值) 元组避免 int 与 str 直接比较
        return [
            (0, int(token)) if token.isdigit() else (1, token.lower())
            for token in re.split(r"(\d+)", rel)
        ]

    files = [
        Path(root) / name
        for root, _dirs, names in os.walk(source_dir)
        for name in names
        if (Path(root) / name).suffix.lower() in _IMAGE_EXTENSIONS
    ]
    files.sort(key=natural_key)
    return files


@dataclass
class PackResult:
    """打包结果"""

    success: bool
    output_path: Path | None
    format: str
    encrypted: bool
    output_paths: list[Path] = field(default_factory=list)
    error_message: str | None = None


class JMPacker:
    """JMComic 打包器"""

    def __init__(self, pack_format: str = "zip", password: str = ""):
        """
        初始化打包器

        Args:
            pack_format: 打包格式 (zip/pdf/none)
            password: 加密密码，为空则不加密
        """
        self.pack_format = pack_format.lower()
        self.password = password

    def pack(
        self,
        source_dir: Path,
        output_name: str,
        output_dir: Path | None = None,
        max_file_size_mb: int = 0,
    ) -> PackResult:
        """
        打包目录

        Args:
            source_dir: 源目录
            output_name: 输出文件名（不含扩展名）
            output_dir: 输出目录，默认为源目录的父目录
            max_file_size_mb: 文件大小上限（MB），>0 时自动分组打包；0=单文件

        Returns:
            PackResult 打包结果（output_paths 包含所有卷文件路径）
        """
        max_bytes = int(max_file_size_mb) * 1024 * 1024 if max_file_size_mb else 0

        if not source_dir.exists():
            return PackResult(
                success=False,
                output_path=None,
                format=self.pack_format,
                encrypted=bool(self.password),
                error_message=f"源目录不存在: {source_dir}",
            )

        if output_dir is None:
            output_dir = source_dir.parent

        output_dir.mkdir(parents=True, exist_ok=True)

        if self.pack_format == "zip":
            return self._pack_zip(source_dir, output_name, output_dir, max_bytes)
        elif self.pack_format == "pdf":
            return self._pack_pdf(source_dir, output_name, output_dir, max_bytes)
        elif self.pack_format == "long_img":
            return self._pack_long_img(source_dir, output_name, output_dir, max_bytes)
        elif self.pack_format == "none":
            return PackResult(
                success=True,
                output_path=source_dir,
                output_paths=[source_dir],
                format="none",
                encrypted=False,
            )
        else:
            return PackResult(
                success=False,
                output_path=None,
                format=self.pack_format,
                encrypted=False,
                error_message=f"不支持的打包格式: {self.pack_format}",
            )

    def _pack_zip(
        self, source_dir: Path, output_name: str, output_dir: Path, max_bytes: int = 0
    ) -> PackResult:
        """打包为 ZIP；max_bytes > 0 时分卷打包，每卷独立可读"""
        # 请求了加密但缺少 pyzipper：失败关闭，不静默产出未加密压缩包
        if self.password and not PYZIPPER_AVAILABLE:
            return PackResult(
                success=False,
                output_path=None,
                format="zip",
                encrypted=False,
                error_message=(
                    "已设置打包密码但未安装 pyzipper，无法生成加密 ZIP；"
                    "请安装 pyzipper 或清空打包密码"
                ),
            )

        image_files = _collect_images_sorted(source_dir)
        if not image_files:
            return PackResult(
                success=False,
                output_path=None,
                format="zip",
                encrypted=False,
                error_message="未找到图片文件",
            )

        groups = self._split_files_into_size_groups(image_files, max_bytes)

        output_paths: list[Path] = []
        try:
            for i, group in enumerate(groups, 1):
                if len(groups) > 1:
                    filename = f"{output_name}_part{i}.zip"
                else:
                    filename = f"{output_name}.zip"
                group_path = output_dir / filename

                if self.password:
                    # 使用pyzipper创建加密ZIP
                    with pyzipper.AESZipFile(
                        group_path,
                        "w",
                        compression=pyzipper.ZIP_DEFLATED,
                        encryption=pyzipper.WZ_AES,
                    ) as zf:
                        zf.setpassword(self.password.encode("utf-8"))
                        for fp in group:
                            zf.write(fp, fp.relative_to(source_dir))
                else:
                    # 使用标准库创建普通ZIP
                    import zipfile

                    with zipfile.ZipFile(
                        group_path, "w", zipfile.ZIP_DEFLATED
                    ) as zf:
                        for fp in group:
                            zf.write(fp, fp.relative_to(source_dir))

                output_paths.append(group_path)

            return PackResult(
                success=True,
                output_path=output_paths[0],
                output_paths=output_paths,
                format="zip",
                encrypted=bool(self.password),
            )

        except Exception as e:
            # 清理已生成的部分文件
            for p in output_paths:
                self.cleanup(p)
            return PackResult(
                success=False,
                output_path=None,
                format="zip",
                encrypted=False,
                error_message=str(e),
            )

    def _pack_pdf(
        self, source_dir: Path, output_name: str, output_dir: Path, max_bytes: int = 0
    ) -> PackResult:
        """打包为 PDF；max_bytes > 0 时分卷打包，每卷独立可读"""
        if not PYMUPDF_AVAILABLE:
            return PackResult(
                success=False,
                output_path=None,
                format="pdf",
                encrypted=False,
                error_message="pymupdf 库未安装，无法创建PDF",
            )

        # 收集所有图片文件（自然顺序，正确跨章节排序）
        image_files = _collect_images_sorted(source_dir)

        if not image_files:
            return PackResult(
                success=False,
                output_path=None,
                format="pdf",
                encrypted=False,
                error_message="未找到图片文件",
            )

        groups = self._split_files_into_size_groups(image_files, max_bytes)

        output_paths: list[Path] = []
        try:
            for i, group in enumerate(groups, 1):
                if len(groups) > 1:
                    filename = f"{output_name}_part{i}.pdf"
                else:
                    filename = f"{output_name}.pdf"
                group_path = output_dir / filename

                # 创建PDF
                doc = fitz.open()

                for img_path in group:
                    try:
                        img = fitz.open(img_path)
                        pdfbytes = img.convert_to_pdf()
                        img.close()

                        imgpdf = fitz.open("pdf", pdfbytes)
                        doc.insert_pdf(imgpdf)
                        imgpdf.close()
                    except Exception:
                        continue  # 跳过无法处理的图片

                if doc.page_count == 0:
                    doc.close()
                    continue  # 该组无可处理图片，跳过

                # 保存PDF（可选加密）
                if self.password:
                    doc.save(
                        group_path,
                        encryption=fitz.PDF_ENCRYPT_AES_256,
                        owner_pw=self.password,
                        user_pw=self.password,
                        permissions=fitz.PDF_PERM_ACCESSIBILITY,
                    )
                else:
                    doc.save(group_path)

                doc.close()
                output_paths.append(group_path)

            if not output_paths:
                return PackResult(
                    success=False,
                    output_path=None,
                    format="pdf",
                    encrypted=False,
                    error_message="无法创建PDF页面",
                )

            return PackResult(
                success=True,
                output_path=output_paths[0],
                output_paths=output_paths,
                format="pdf",
                encrypted=bool(self.password),
            )

        except Exception as e:
            for p in output_paths:
                self.cleanup(p)
            return PackResult(
                success=False,
                output_path=None,
                format="pdf",
                encrypted=False,
                error_message=str(e),
            )

    def _pack_long_img(
        self, source_dir: Path, output_name: str, output_dir: Path, max_bytes: int = 0
    ) -> PackResult:
        """打包为长图：纵向拼接图片，过长自动分段；超出大小上限时分卷打包"""
        if not PIL_AVAILABLE:
            return PackResult(
                success=False,
                output_path=None,
                format="long_img",
                encrypted=False,
                error_message="Pillow 库未安装，无法生成长图",
            )

        # 收集所有图片文件（自然顺序，保证章节/页码阅读顺序）
        image_files = _collect_images_sorted(source_dir)

        if not image_files:
            return PackResult(
                success=False,
                output_path=None,
                format="long_img",
                encrypted=False,
                error_message="未找到图片文件",
            )

        try:
            strips = self._build_long_strips(image_files)
        except Exception as e:
            return PackResult(
                success=False,
                output_path=None,
                format="long_img",
                encrypted=False,
                error_message=str(e),
            )

        if not strips:
            return PackResult(
                success=False,
                output_path=None,
                format="long_img",
                encrypted=False,
                error_message="无法生成长图",
            )

        try:
            # 单段：直接输出一张长图（strip 已有高度限制，通常已控制在合理大小）
            if len(strips) == 1:
                output_path = output_dir / f"{output_name}.png"
                strips[0].save(output_path)
                strips[0].close()
                return PackResult(
                    success=True,
                    output_path=output_path,
                    output_paths=[output_path],
                    format="long_img",
                    encrypted=False,
                )

            # 多段：先落地为多张 png，再复用 ZIP 打包逻辑（支持加密和分卷）
            import tempfile

            tmp_dir = Path(tempfile.mkdtemp(prefix="jm_longimg_"))
            try:
                for index, strip in enumerate(strips, 1):
                    strip.save(tmp_dir / f"{output_name}_{index:03d}.png")
                    strip.close()
                zip_result = self._pack_zip(
                    tmp_dir, output_name, output_dir, max_bytes
                )
                return PackResult(
                    success=zip_result.success,
                    output_path=zip_result.output_path,
                    output_paths=zip_result.output_paths,
                    format="long_img",
                    encrypted=zip_result.encrypted,
                    error_message=zip_result.error_message,
                )
            finally:
                self.cleanup(tmp_dir)
        except Exception as e:
            return PackResult(
                success=False,
                output_path=None,
                format="long_img",
                encrypted=False,
                error_message=str(e),
            )

    def _build_long_strips(self, image_files: list[Path]) -> list:
        """把图片缩放到统一宽度并按高度/数量上限分段，返回拼接后的 PIL 图片列表"""
        strips = []
        batch: list = []
        batch_height = 0

        def flush_batch() -> None:
            nonlocal batch, batch_height
            if batch:
                strips.append(self._merge_vertical(batch))
                batch = []
                batch_height = 0

        for file_path in image_files:
            try:
                with Image.open(file_path) as raw:
                    scaled_height = max(
                        1, int(raw.height * _LONG_IMG_WIDTH / raw.width)
                    )
                    img = raw.convert("RGB").resize((_LONG_IMG_WIDTH, scaled_height))
            except Exception:
                continue  # 跳过无法读取的图片

            if batch and (
                batch_height + img.height > _LONG_IMG_MAX_STRIP_HEIGHT
                or len(batch) >= _LONG_IMG_MAX_PER_STRIP
            ):
                flush_batch()

            batch.append(img)
            batch_height += img.height

        flush_batch()
        return strips

    @staticmethod
    def _merge_vertical(images: list):
        """把同宽度的图片纵向拼成一张，并释放分块图片占用的内存"""
        total_height = sum(im.height for im in images)
        canvas = Image.new("RGB", (_LONG_IMG_WIDTH, total_height), (255, 255, 255))
        offset_y = 0
        for im in images:
            canvas.paste(im, (0, offset_y))
            offset_y += im.height
            im.close()
        return canvas

    @staticmethod
    def _split_files_into_size_groups(
        files: list[Path], max_bytes: int
    ) -> list[list[Path]]:
        """按累计文件字节数将文件列表拆分为多组，每组总大小 < max_bytes。

        单文件超过 max_bytes 时自成一组（无法再拆分），保证不会丢文件。
        max_bytes <= 0 时返回原始列表作为单独一组。
        """
        if max_bytes <= 0 or not files:
            return [files]

        groups: list[list[Path]] = []
        current_group: list[Path] = []
        current_size = 0

        for fp in files:
            f_size = fp.stat().st_size
            if f_size > max_bytes:
                logger.warning(
                    f"单个图片文件超过分卷阈值，将单独成卷: {fp.name} "
                    f"({f_size / 1024 / 1024:.2f}MB > "
                    f"{max_bytes / 1024 / 1024:.2f}MB)"
                )
            if current_group and current_size + f_size > max_bytes:
                groups.append(current_group)
                current_group = []
                current_size = 0
            current_group.append(fp)
            current_size += f_size

        if current_group:
            groups.append(current_group)

        return groups

    @staticmethod
    def cleanup(path: Path) -> bool:
        """
        清理文件或目录

        Args:
            path: 要删除的路径

        Returns:
            是否成功删除
        """
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
            return True
        except Exception:
            return False
