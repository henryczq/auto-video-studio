import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List


@dataclass
class Caption:
    id: int
    start: float
    end: float
    text: str


def parse_srt_time(value: str) -> float:
    match = re.fullmatch(r"(\d\d):(\d\d):(\d\d)[,\.](\d\d\d)", value.strip())
    if not match:
        raise ValueError(f"invalid srt time: {value}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def format_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def read_srt(path: Path) -> List[Caption]:
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    blocks = re.split(r"\n\s*\n", content.strip())
    captions: List[Caption] = []
    for idx, block in enumerate(blocks, start=1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_line_idx = 0
        if "-->" not in lines[0] and len(lines) > 1:
            time_line_idx = 1
        if "-->" not in lines[time_line_idx]:
            continue
        start_raw, end_raw = [
            part.strip() for part in lines[time_line_idx].split("-->", 1)
        ]
        text = "".join(lines[time_line_idx + 1 :])
        if not text:
            continue
        captions.append(
            Caption(idx, parse_srt_time(start_raw), parse_srt_time(end_raw), text)
        )
    return captions


def write_srt(captions: List[Caption], path: Path) -> None:
    lines = []
    for caption in captions:
        lines.append(str(caption.id))
        lines.append(
            f"{format_srt_time(caption.start)} --> {format_srt_time(caption.end)}"
        )
        lines.append(caption.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def captions_to_json(captions: List[Caption]) -> List[dict]:
    return [asdict(c) for c in captions]


def json_to_captions(data: List[dict]) -> List[Caption]:
    captions = []
    for idx, item in enumerate(data, start=1):
        captions.append(
            Caption(
                id=item.get("id", idx),
                start=float(item["start"]),
                end=float(item["end"]),
                text=item["text"],
            )
        )
    return captions


def read_json(path: Path) -> List[Caption]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json_to_captions(data)


def write_json(captions: List[Caption], path: Path) -> None:
    path.write_text(
        json.dumps(captions_to_json(captions), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_terms(captions: List[Caption], terms: dict) -> List[Caption]:
    result = []
    sorted_terms = sorted(terms.items(), key=lambda item: len(item[0]), reverse=True)
    for caption in captions:
        text = caption.text
        for src, dst in sorted_terms:
            text = text.replace(src, dst)
        result.append(Caption(caption.id, caption.start, caption.end, text))
    return result


def captions_to_srt(captions_data: List[dict]) -> str:
    lines = []
    for idx, cap in enumerate(captions_data, start=1):
        lines.append(str(idx))
        lines.append(
            f"{format_srt_time(cap['start'])} --> {format_srt_time(cap['end'])}"
        )
        lines.append(cap["text"])
        lines.append("")
    return "\n".join(lines)
