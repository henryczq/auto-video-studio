import re
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from services.job_store import get_job_dir


def _parse_timestamp(value: str) -> float:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("请输入封面时间点")
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return float(raw)

    parts = raw.split(":")
    if not 2 <= len(parts) <= 3:
        raise ValueError("时间格式不正确，支持 3.5、00:03.5、00:01:23")

    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("时间格式不正确，支持 3.5、00:03.5、00:01:23") from exc

    if len(numbers) == 2:
        minutes, seconds = numbers
        total = minutes * 60 + seconds
    else:
        hours, minutes, seconds = numbers
        total = hours * 3600 + minutes * 60 + seconds

    if total < 0:
        raise ValueError("时间点不能小于 0")
    return total


def _resolve_job_file(job_id: str, path: str) -> Path:
    job_dir = get_job_dir(job_id).resolve()
    raw_path = Path((path or "").strip())
    if not raw_path:
        raise ValueError("未找到可截取封面的源视频")

    resolved = raw_path.resolve() if raw_path.is_absolute() else (job_dir / raw_path).resolve()
    if not resolved.is_relative_to(job_dir):
        raise ValueError("视频文件必须位于当前任务目录内")
    if not resolved.exists():
        raise ValueError(f"视频文件不存在: {resolved}")
    return resolved


def _save_image_as_jpeg(image: Image.Image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = ImageOps.exif_transpose(image)
    if image.mode not in {"RGB", "L"}:
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "RGBA":
            background.paste(image, mask=image.getchannel("A"))
        else:
            background.paste(image.convert("RGB"))
        image = background
    else:
        image = image.convert("RGB")
    tmp_path = output_path.with_name(f".{output_path.name}.tmp")
    image.save(tmp_path, format="JPEG", quality=92, optimize=True)
    tmp_path.replace(output_path)


def _font_path(bold: bool = False) -> str:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _font_path(bold=bold)
    if path:
        return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines: list[str] = []
    for raw_line in raw_lines:
        current = ""
        for char in raw_line:
            candidate = current + char
            try:
                bbox = draw.textbbox((0, 0), candidate, font=font)
                width = bbox[2] - bbox[0]
            except Exception:
                width = font.getlength(candidate) if hasattr(font, 'getlength') else len(candidate) * 20
            if current and width > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def _get_text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    """安全获取文字尺寸，处理 font.getlength 可能卡住的问题"""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        width = font.getlength(text) if hasattr(font, 'getlength') else len(text) * 20
        height = int(font.size * 1.2) if hasattr(font, 'size') else 24
        return (width, height)


def generate_cover_from_video(job_id: str, video_path: str, timestamp: str, title: str = None, font_size: str = "medium", font_color: str = "#ffffff") -> dict:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[Cover] job_id={job_id}, font_size={font_size}, font_color={font_color}")

    source_video = _resolve_job_file(job_id, video_path)
    seconds = _parse_timestamp(timestamp)
    job_dir = get_job_dir(job_id).resolve()
    output_name = "publish_cover.jpg"
    output_path = job_dir / output_name

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(source_video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not output_path.exists():
        error = (result.stderr or result.stdout or "ffmpeg 截取封面失败").strip()
        raise ValueError(error[-1000:])

    # 如果有标题，生成带标题的封面
    cover_title = (title or "").strip()
    if cover_title:
        return generate_text_cover(job_id, output_name, cover_title, font_size, font_color)

    return {
        "thumbnail": output_name,
        "path": str(output_path),
        "timestamp": seconds,
        "source_video": source_video.name,
    }


def save_uploaded_cover(job_id: str, filename: str, content: bytes) -> dict:
    if not content:
        raise ValueError("上传文件为空")

    job_dir = get_job_dir(job_id).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    output_name = "publish_cover_uploaded.jpg"
    output_path = job_dir / output_name

    try:
        with Image.open(BytesIO(content)) as image:
            _save_image_as_jpeg(image, output_path)
    except Exception as exc:
        raise ValueError("封面文件不是可识别的图片") from exc

    return {
        "thumbnail": output_name,
        "path": str(output_path),
        "source_filename": filename,
    }


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    """解析 hex 颜色为 RGB 元组"""
    hex_color = (hex_color or "#ffffff").strip()
    if hex_color.startswith('#'):
        hex_color = hex_color[1:]
    if len(hex_color) == 3:
        hex_color = hex_color[0] * 2 + hex_color[1] * 2 + hex_color[2] * 2
    if len(hex_color) != 6:
        return (255, 255, 255)
    try:
        return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def generate_text_cover(job_id: str, thumbnail: str, text: str, font_size: str = "medium", font_color: str = "#ffffff") -> dict:
    cover_text = (text or "").strip()
    if not cover_text:
        raise ValueError("请输入要打到封面上的文字")

    job_dir = get_job_dir(job_id).resolve()

    # 确定要使用的源封面图（优先使用传入的 thumbnail，否则用 publish_cover.jpg）
    if thumbnail and thumbnail.strip():
        thumbnail_name = thumbnail.strip()
    else:
        thumbnail_name = "publish_cover.jpg"

    source_path = _resolve_job_file(job_id, thumbnail_name)
    if not source_path.exists():
        raise ValueError(f"未找到可用的封面图: {thumbnail_name}，请先生成封面截图")
    output_name = "publish_cover_text.jpg"
    output_path = job_dir / output_name

    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")

    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    margin = max(28, int(width * 0.07))
    max_text_width = width - margin * 2

    # 根据 font_size 参数调整基础字号
    base_size = int(width * 0.095)
    if font_size == "small":
        scale = 0.7
    elif font_size == "large":
        scale = 1.4
    elif font_size == "xlarge":
        scale = 1.8
    else:  # medium
        scale = 1.0
    current_font_size = max(28, min(120, int(base_size * scale)))

    font = _load_font(current_font_size, bold=True)

    # 解析字体颜色（确保是有效的 RGB）
    text_color_rgb = _parse_hex_color(font_color)

    # 文字换行
    lines = _wrap_text(cover_text, font, max_text_width, draw)
    while len(lines) > 4 and current_font_size > 26:
        current_font_size -= 4
        font = _load_font(current_font_size, bold=True)
        lines = _wrap_text(cover_text, font, max_text_width, draw)
    lines = lines[:4]

    # 计算文字总高度，使其在图片垂直方向居中
    line_heights = [_get_text_size(draw, line, font)[1] for line in lines]
    line_gap = max(10, int(current_font_size * 0.22))
    text_height = sum(line_heights) + line_gap * max(0, len(lines) - 1)

    # 计算起始 y 坐标，使文字块在图片垂直居中
    y = (height - text_height) // 2

    # 绘制文字（水平和垂直居中）
    for line in lines:
        line_width, line_height = _get_text_size(draw, line, font)
        x = (width - line_width) // 2
        # 黑色阴影
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 160))
        # 主文字（使用用户选择的颜色，RGBA 格式）
        draw.text((x, y), line, font=font, fill=(*text_color_rgb, 255))
        y += line_height + line_gap

    _save_image_as_jpeg(image, output_path)

    return {
        "thumbnail": output_name,
        "path": str(output_path),
        "source_thumbnail": source_path.name,
        "text": cover_text,
        "font_size": font_size,
        "font_color": font_color,
    }
