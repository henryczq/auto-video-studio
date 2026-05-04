"""Subtitle rendering - SRT/ASS generation from caption data."""

import re
from pathlib import Path
from typing import List, Optional


class SubtitleRender:
    """Renders captions to various subtitle formats."""

    @staticmethod
    def format_srt_time(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        secs = (total_ms % 60_000) // 1000
        ms = total_ms % 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    @staticmethod
    def format_ass_time(seconds: float) -> str:
        total_cs = max(0, int(round(seconds * 100)))
        hours = total_cs // 360_000
        minutes = (total_cs % 360_000) // 6000
        secs = (total_cs % 6000) // 100
        cs = total_cs % 100
        return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"

    def render_srt(self, captions: List[dict], output_path: Optional[Path] = None) -> str:
        lines = []
        for i, cap in enumerate(captions, start=1):
            start = self.format_srt_time(cap["start"])
            end = self.format_srt_time(cap["end"])
            text = cap["text"].replace("\n", " ")
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        content = "\n".join(lines)
        if output_path:
            output_path.write_text(content, encoding="utf-8-sig")
        return content

    def render_ass(self, captions: List[dict], output_path: Optional[Path] = None,
                   style_name: str = "Default", font_size: int = 48) -> str:
        lines = [
            "[Script Info]",
            "Title: Generated Subtitles",
            "ScriptType: v4.00+",
            "Collisions: Normal",
            "PlayDepth: 0",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: {style_name},Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,"
            "100,100,0,0,1,2,2,2,10,10,10,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        for cap in captions:
            start = self.format_ass_time(cap["start"])
            end = self.format_ass_time(cap["end"])
            text = cap["text"].replace("\n", "\\N")
            text = text.replace("<i>", "{\\i1}").replace("</i>", "{\\i0}")
            text = text.replace("<b>", "{\\b1}").replace("</b>", "{\\b0}")
            lines.append(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}")
        content = "\n".join(lines)
        if output_path:
            output_path.write_text(content, encoding="utf-8-sig")
        return content

    def parse_srt(self, content: str) -> List[dict]:
        captions = []
        blocks = re.split(r"\n\s*\n", content.strip())
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 2:
                continue
            try:
                timeparts = lines[1].split("-->")
                start = self._parse_srt_time(timeparts[0].strip())
                end = self._parse_srt_time(timeparts[1].strip())
                text = " ".join(lines[2:])
                captions.append({"start": start, "end": end, "text": text})
            except (ValueError, IndexError):
                continue
        return captions

    def _parse_srt_time(self, time_str: str) -> float:
        match = re.fullmatch(r"(\d\d):(\d\d):(\d\d)[,\.](\d\d\d)", time_str.strip())
        if not match:
            raise ValueError(f"invalid srt time: {time_str}")
        hours, minutes, seconds, millis = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds + millis / 1000


subtile_render = SubtitleRender()
