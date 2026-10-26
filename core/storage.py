"""Storage & validation."""

from __future__ import annotations

import base64
import io
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 100_000_000


def decode_b64(data: str) -> bytes:
    encoded = (
        data.split(",", 1)[1]
        if data.strip().startswith("data:") and "," in data
        else data
    )
    # remove whitespace
    compact = "".join(ch for ch in encoded if not ch.isspace())
    if len(compact) > 96 * 1024 * 1024:
        raise ValueError("图片 Base64 数据超过大小限制")
    raw = base64.b64decode(compact)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 64 MiB 大小限制")
    return raw


def format_info(data: bytes) -> tuple[str, str, int, int]:
    if not data:
        raise ValueError("供应商返回了空图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 64 MiB 大小限制")
    try:
        fmt = Image.open(io.BytesIO(data)).format
    except Exception:
        raise ValueError("无法识别真实图片格式")
    fmt = (fmt or "").upper()
    mapping = {
        "PNG": ("image/png", "png"),
        "JPEG": ("image/jpeg", "jpg"),
        "JPG": ("image/jpeg", "jpg"),
        "GIF": ("image/gif", "gif"),
        "WEBP": ("image/webp", "webp"),
        "BMP": ("image/bmp", "bmp"),
    }
    if fmt not in mapping:
        raise ValueError("当前仅支持 PNG、JPEG、GIF、WebP 和 BMP 图片")
    mime, ext = mapping[fmt]
    try:
        im = Image.open(io.BytesIO(data))
        w, h = im.size
    except Exception as e:
        raise ValueError(f"读取图片尺寸失败：{e}")
    if w == 0 or h == 0 or w * h > MAX_PIXELS:
        raise ValueError(f"图片尺寸不安全：{w}x{h}")
    return mime, ext, w, h


def get_whitelist_temp_dir(data_dir: Path | None = None) -> Path:
    """获取落在 AstrBot 发送文件白名单内的目录（data/temp、/tmp/.astrbot、workspace）。

    优先顺序：
    1. AstrBot 官方路径接口 get_astrbot_temp_path() (即 <root>/data/temp)
    2. 从 data_dir 向上定位并推导得到的 data/temp
    3. 系统临时共享目录下的 .astrbot (Linux 上为 /tmp/.astrbot)
    4. 当前工作目录下的 data/temp 或 workspace
    """
    candidates: list[Path] = []

    # 1. 尝试直接导入 AstrBot 官方路径工具
    try:
        from astrbot.core.utils.astrbot_path import (
            get_astrbot_system_tmp_path,
            get_astrbot_temp_path,
        )

        candidates.append(Path(get_astrbot_temp_path()).resolve())
        candidates.append(Path(get_astrbot_system_tmp_path()).resolve())
    except Exception:
        pass

    # 2. 从 data_dir 向上追溯查找 AstrBot 根目录中的 data/temp
    if data_dir is not None:
        try:
            curr = data_dir.resolve()
            while curr != curr.parent:
                if curr.name == "data":
                    candidates.append((curr / "temp").resolve())
                    break
                if (curr / "data").is_dir():
                    candidates.append((curr / "data" / "temp").resolve())
                    break
                curr = curr.parent
        except Exception:
            pass

    # 3. /tmp/.astrbot (Linux/POSIX 标准) 或系统临时目录下的 .astrbot
    if os.name != "nt":
        candidates.append(Path("/tmp/.astrbot"))
    try:
        candidates.append((Path(tempfile.gettempdir()) / ".astrbot").resolve())
    except Exception:
        pass

    # 4. 当前工作空间下的 data/temp 与 workspace
    try:
        cwd = Path.cwd().resolve()
        candidates.append((cwd / "data" / "temp").resolve())
        candidates.append((cwd / "workspace").resolve())
    except Exception:
        pass

    # 尝试并校验候选目录的可写性
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            test_file = cand / f".astr_write_test_{uuid.uuid4().hex[:6]}"
            test_file.write_bytes(b"")
            test_file.unlink(missing_ok=True)
            return cand
        except Exception:
            continue

    # 兜底降级为系统的临时目录
    fallback = Path(tempfile.gettempdir()).resolve() / ".astrbot"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    except Exception:
        return data_dir if data_dir is not None else Path(tempfile.gettempdir()).resolve()


def persist_image(
    data_dir: Path,
    data: bytes,
    remote_url: str | None = None,
    revised_prompt: str | None = None,
) -> dict:
    """持久化保存图片：
    1. 永久副本：保存在插件自身的 data_dir/generated-images/YYYYMMDD 下，确保数据永不丢失且 WebUI 可查；
    2. 白名单分发副本：同时落盘到 AstrBot 发文件白名单目录（data/temp、/tmp/.astrbot、workspace）下，
       并将该白名单路径赋值给 absolute_path 返回给 AI，确保 send_message_to_user 不会因路径白名单被拒。
    """
    mime, ext, w, h = format_info(data)
    date_dir = datetime.now().strftime("%Y%m%d")

    # 1. 永久归档存储（避免数据丢失）
    permanent_dir = data_dir / "generated-images" / date_dir
    permanent_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4()}.{ext}"
    permanent_path = permanent_dir / fname
    permanent_path.write_bytes(data)

    # 2. 落在发文件白名单内的路径（供 send_message_to_user 发送）
    whitelist_dir = get_whitelist_temp_dir(data_dir)
    whitelist_path = whitelist_dir / fname
    try:
        whitelist_path.write_bytes(data)
    except Exception:
        # 若写入白名单目录失败，则回退使用永久存储路径
        whitelist_path = permanent_path

    # relative_path 依然相对于 data_dir，供插件 WebUI / list_generated 检索
    rel = permanent_path.relative_to(data_dir).as_posix()
    markdown = f"![生成图片]({rel})"

    return {
        "relative_path": rel,
        "remote_url": remote_url,
        "markdown": markdown,
        "mime": mime,
        "width": w,
        "height": h,
        "revised_prompt": revised_prompt,
        "permanent_path": str(permanent_path),
        # 返回给 AI 的绝对路径位于白名单内
        "absolute_path": str(whitelist_path),
    }
