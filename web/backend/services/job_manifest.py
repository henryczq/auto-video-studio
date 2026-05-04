"""Job Manifest - tracks all artifacts produced by job processing.

Each job directory contains a manifest.json that records:
- Job metadata and versions
- All derived outputs and their sources
- Timestamps for tracking staleness
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


MANIFEST_FILENAME = "manifest.json"


@dataclass
class Artifact:
    path: str
    type: str
    source_version: int = 0
    created_at: Optional[str] = None
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None


@dataclass
class JobManifest:
    job_id: str
    created_at: str
    updated_at: str
    captions_version: int = 0
    trim_version: int = 0
    tts_version: int = 0
    compose_version: int = 0
    artifacts: Dict[str, Artifact] = None

    def __post_init__(self):
        if self.artifacts is None:
            self.artifacts = {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobManifest":
        artifacts = {
            k: Artifact(**v) if isinstance(v, dict) else v
            for k, v in data.get("artifacts", {}).items()
        }
        return cls(
            job_id=data["job_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            captions_version=data.get("captions_version", 0),
            trim_version=data.get("trim_version", 0),
            tts_version=data.get("tts_version", 0),
            compose_version=data.get("compose_version", 0),
            artifacts=artifacts,
        )

    @classmethod
    def load(cls, job_dir: Path) -> Optional["JobManifest"]:
        manifest_path = job_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def save(self, job_dir: Path) -> None:
        manifest_path = job_dir / MANIFEST_FILENAME
        self.updated_at = datetime.now().isoformat()
        manifest_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_artifact(self, name: str, path: Path, artifact_type: str) -> None:
        self.artifacts[name] = Artifact(
            path=str(path.relative_to(path.parent.parent)),
            type=artifact_type,
            created_at=datetime.now().isoformat(),
            size_bytes=path.stat().st_size if path.exists() else None,
        )

    def remove_artifact(self, name: str) -> None:
        if name in self.artifacts:
            del self.artifacts[name]

    def get_artifact(self, name: str) -> Optional[Artifact]:
        return self.artifacts.get(name)

    def is_stale(self, derive_type: str) -> bool:
        current = self.captions_version
        if derive_type == "trim":
            return self.trim_version == 0 or self.trim_version < current
        elif derive_type == "tts":
            return self.tts_version == 0 or self.tts_version < current
        elif derive_type == "compose":
            return self.compose_version == 0 or self.compose_version < current
        return False

    def invalidate(self, derive_type: str) -> None:
        if derive_type == "trim":
            self.trim_version = 0
        elif derive_type == "tts":
            self.tts_version = 0
        elif derive_type == "compose":
            self.compose_version = 0


def ensure_manifest(job_dir: Path, job_id: str) -> JobManifest:
    manifest = JobManifest.load(job_dir)
    if manifest is None:
        now = datetime.now().isoformat()
        manifest = JobManifest(
            job_id=job_id,
            created_at=now,
            updated_at=now,
        )
        manifest.save(job_dir)
    return manifest


def invalidate_derived_outputs(job_dir: Path) -> None:
    manifest = JobManifest.load(job_dir)
    if manifest:
        manifest.captions_version += 1
        manifest.invalidate("trim")
        manifest.invalidate("tts")
        manifest.invalidate("compose")
        manifest.save(job_dir)


def record_trim_complete(job_dir: Path) -> None:
    manifest = ensure_manifest(job_dir, job_dir.name)
    manifest.trim_version = manifest.captions_version
    manifest.save(job_dir)


def record_tts_complete(job_dir: Path) -> None:
    manifest = ensure_manifest(job_dir, job_dir.name)
    manifest.tts_version = manifest.captions_version
    manifest.save(job_dir)


def record_compose_complete(job_dir: Path) -> None:
    manifest = ensure_manifest(job_dir, job_dir.name)
    manifest.compose_version = manifest.captions_version
    manifest.save(job_dir)
