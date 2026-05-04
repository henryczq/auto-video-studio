"""Caption store - unified source/working/derived model for captions.

File naming convention in job directory:
- captions.source.json: Original ASR output (read-only, never modified)
- captions.working.json: Current working captions (all edits applied here)
- captions.derived.srt: Final SRT for video (derived from working)
- captions.derived.ass: ASS subtitle file (derived from working)
- captions.trimmed.json: Trimmed captions after video cutting (derived from working)
- captions.cut_marks.json: Cut marks for video trimming
"""

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime


@dataclass
class Caption:
    id: int
    start: float
    end: float
    text: str


@dataclass
class CaptionVersions:
    """Track versions of derived outputs to detect staleness."""
    captions: int = 0  # Incremented when working captions change
    trim: int = 0  # Incremented when trim is applied
    tts: int = 0  # Incremented when TTS segments generated


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


class CaptionStore:
    """Manages captions using source/working/derived model."""
    
    def __init__(self, job_dir: Path):
        self.job_dir = Path(job_dir)
        self.versions = CaptionVersions()
        self._load_versions()
    
    @property
    def source_path(self) -> Path:
        """Original ASR captions (read-only)."""
        return self.job_dir / "captions.source.json"
    
    @property
    def working_path(self) -> Path:
        """Current working captions (editable)."""
        return self.job_dir / "captions.working.json"
    
    @property
    def derived_srt_path(self) -> Path:
        """Final SRT derived from working captions."""
        return self.job_dir / "captions.derived.srt"
    
    @property
    def derived_ass_path(self) -> Path:
        """ASS subtitle file derived from working captions."""
        return self.job_dir / "captions.derived.ass"
    
    @property
    def trimmed_path(self) -> Path:
        """Trimmed captions after video cutting."""
        return self.job_dir / "captions.trimmed.json"
    
    @property
    def cut_marks_path(self) -> Path:
        """Cut marks for video trimming."""
        return self.job_dir / "captions.cut_marks.json"
    
    @property
    def versions_path(self) -> Path:
        """Caption versions tracking file."""
        return self.job_dir / "captions.versions.json"
    
    def _load_versions(self) -> None:
        """Load versions from file."""
        if self.versions_path.exists():
            data = json.loads(self.versions_path.read_text(encoding="utf-8"))
            self.versions = CaptionVersions(
                captions=data.get("captions", 0),
                trim=data.get("trim", 0),
                tts=data.get("tts", 0),
            )
    
    def _save_versions(self) -> None:
        """Save versions to file."""
        data = {
            "captions": self.versions.captions,
            "trim": self.versions.trim,
            "tts": self.versions.tts,
        }
        self.versions_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def initialize_from_srt(self, srt_path: Path) -> None:
        """Initialize source and working captions from an SRT file.
        
        This is called when ASR output is first imported.
        """
        captions = read_srt(srt_path)
        write_json(captions, self.source_path)
        write_json(captions, self.working_path)
        self.versions.captions = 1
        self._save_versions()
    
    def get_source(self) -> Optional[List[Caption]]:
        """Get source captions (read-only)."""
        if not self.source_path.exists():
            return None
        return read_json(self.source_path)
    
    def get_working(self) -> Optional[List[Caption]]:
        """Get working captions."""
        if not self.working_path.exists():
            return None
        return read_json(self.working_path)
    
    def save_working(self, captions: List[Caption]) -> None:
        """Save working captions and increment version."""
        write_json(captions, self.working_path)
        self.versions.captions += 1
        self._save_versions()
        self._invalidate_derived()
    
    def _invalidate_derived(self) -> None:
        """Mark derived outputs as stale (don't delete, just increment versions)."""
        self.versions.trim = 0
        self.versions.tts = 0
        self._save_versions()
    
    def generate_derived_srt(self) -> Path:
        """Generate final SRT from working captions."""
        captions = self.get_working()
        if captions is None:
            raise ValueError("No working captions to generate SRT from")
        write_srt(captions, self.derived_srt_path)
        return self.derived_srt_path
    
    def get_trimmed(self) -> Optional[List[Caption]]:
        """Get trimmed captions."""
        if not self.trimmed_path.exists():
            return None
        return read_json(self.trimmed_path)
    
    def save_trimmed(self, captions: List[Caption]) -> None:
        """Save trimmed captions and increment trim version."""
        write_json(captions, self.trimmed_path)
        self.versions.trim += 1
        self._save_versions()
    
    def get_cut_marks(self) -> List[dict]:
        """Get cut marks."""
        if not self.cut_marks_path.exists():
            return []
        return json.loads(self.cut_marks_path.read_text(encoding="utf-8"))
    
    def save_cut_marks(self, marks: List[dict]) -> None:
        """Save cut marks."""
        self.cut_marks_path.write_text(
            json.dumps(marks, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def is_stale(self, derive_type: str) -> bool:
        """Check if a derived output is stale.
        
        Args:
            derive_type: 'trim', 'tts', 'srt', etc.
        
        Returns:
            True if the derived output was generated from an older version
            of the working captions.
        """
        current_captions_version = self.versions.captions
        
        if derive_type == "trim":
            return self.versions.trim == 0 or self.versions.trim < current_captions_version
        elif derive_type == "tts":
            return self.versions.tts == 0 or self.versions.tts < current_captions_version
        elif derive_type == "srt":
            return not self.derived_srt_path.exists() or self.versions.captions > 0
        elif derive_type == "ass":
            return not self.derived_ass_path.exists() or self.versions.captions > 0
        
        return False
    
    def get_status(self) -> Dict[str, bool]:
        """Get staleness status for all derived outputs."""
        return {
            "srt_stale": self.is_stale("srt"),
            "trim_stale": self.is_stale("trim"),
            "tts_stale": self.is_stale("tts"),
            "ass_stale": self.is_stale("ass"),
            "captions_version": self.versions.captions,
            "trim_version": self.versions.trim,
            "tts_version": self.versions.tts,
        }


def apply_terms(captions: List[Caption], terms: dict) -> List[Caption]:
    """Apply replacement terms to captions."""
    result = []
    for cap in captions:
        text = cap.text
        for old, new in terms.items():
            text = text.replace(old, new)
        result.append(Caption(cap.id, cap.start, cap.end, text))
    return result


def migrate_legacy_captions(job_dir: Path) -> CaptionStore:
    """Migrate legacy caption files to new model.
    
    This handles the transition from:
    - captions.initial.json -> captions.source.json
    - captions.edited.json -> captions.working.json (if exists, else copy from source)
    - captions.final.srt -> captions.derived.srt (derived)
    
    Returns:
        CaptionStore with migrated captions.
    """
    store = CaptionStore(job_dir)
    
    initial_path = job_dir / "captions.initial.json"
    edited_path = job_dir / "captions.edited.json"
    final_srt_path = job_dir / "captions.final.srt"
    
    if not store.source_path.exists() and initial_path.exists():
        captions = read_json(initial_path)
        write_json(captions, store.source_path)
    
    if not store.working_path.exists():
        if edited_path.exists():
            captions = read_json(edited_path)
        elif initial_path.exists():
            captions = read_json(initial_path)
        else:
            captions = []
        write_json(captions, store.working_path)
    
    if not store.derived_srt_path.exists() and final_srt_path.exists():
        captions = read_srt(final_srt_path)
        write_srt(captions, store.derived_srt_path)
    
    store.versions.captions = 1
    store._save_versions()
    
    return store
