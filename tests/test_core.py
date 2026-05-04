"""Core regression tests for file processing pipeline.

Tests the most critical file chain:
1. Caption loading and saving (source/working/derived model)
2. Version tracking and staleness detection
3. Subtitle rendering (SRT/ASS generation)
4. Caption transformation (apply_terms, adjust_timing)
"""

import pytest
from pathlib import Path
import tempfile
import json
import shutil
from types import SimpleNamespace

from webapp.services.caption_store import CaptionStore, Caption
from webapp.services.subtitle_render import SubtitleRender
from webapp.services.caption_transform import CaptionTransform
from webapp.services.job_manifest import JobManifest, ensure_manifest, invalidate_derived_outputs
from webapp.routers.jobs_trim import CutMarksSaveRequest, save_cut_marks
from webapp.services.tts import resolve_tts_input_paths
from webapp.services.tts_segments import build_and_store_tts_segments


class TestCaptionStore:
    def test_source_working_derived_model(self, tmp_path):
        store = CaptionStore(tmp_path)
        test_captions = [
            {"id": 1, "start": 0.0, "end": 2.5, "text": "Hello world"},
            {"id": 2, "start": 2.5, "end": 5.0, "text": "Testing captions"},
        ]
        store.save_working(test_captions)
        loaded = store.load_working()
        assert len(loaded) == 2
        assert loaded[0].text == "Hello world"
        assert store.is_stale("trim") is True

    def test_version_tracking(self, tmp_path):
        store = CaptionStore(tmp_path)
        captions = [{"id": 1, "start": 0.0, "end": 1.0, "text": "Test"}]
        store.save_working(captions)
        v1 = store.versions.captions
        store.save_working(captions)
        v2 = store.versions.captions
        assert v2 > v1


class TestSubtitleRender:
    def test_render_srt(self, tmp_path):
        render = SubtitleRender()
        captions = [
            {"start": 0.0, "end": 2.5, "text": "Hello"},
            {"start": 2.5, "end": 5.0, "text": "World"},
        ]
        output = tmp_path / "test.srt"
        content = render.render_srt(captions, output)
        assert output.exists()
        assert "00:00:00,000 --> 00:00:02,500" in content
        assert "Hello" in content

    def test_render_ass(self, tmp_path):
        render = SubtitleRender()
        captions = [
            {"start": 0.0, "end": 2.5, "text": "Hello"},
        ]
        output = tmp_path / "test.ass"
        content = render.render_ass(captions, output)
        assert output.exists()
        assert "[Script Info]" in content
        assert "Hello" in content

    def test_parse_srt(self):
        render = SubtitleRender()
        content = "1\n00:00:00,000 --> 00:00:02,500\nHello\n\n2\n00:00:02,500 --> 00:00:05,000\nWorld\n"
        captions = render.parse_srt(content)
        assert len(captions) == 2
        assert captions[0]["text"] == "Hello"
        assert captions[1]["start"] == 2.5


class TestCaptionTransform:
    def test_apply_terms(self):
        transform = CaptionTransform()
        captions = [
            {"start": 0.0, "end": 1.0, "text": "foo bar"},
        ]
        terms = {"foo": "hello", "bar": "world"}
        result = transform.apply_terms(captions, terms)
        assert result[0]["text"] == "hello world"

    def test_adjust_timing(self):
        transform = CaptionTransform()
        captions = [
            {"start": 10.0, "end": 15.0, "text": "Test"},
        ]
        result = transform.adjust_timing(captions, offset=-10.0)
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 5.0

    def test_filter_by_time_range(self):
        transform = CaptionTransform()
        captions = [
            {"start": 0.0, "end": 5.0, "text": "A"},
            {"start": 10.0, "end": 15.0, "text": "B"},
            {"start": 20.0, "end": 25.0, "text": "C"},
        ]
        result = transform.filter_by_time_range(captions, start=8.0, end=18.0)
        assert len(result) == 1
        assert result[0]["text"] == "B"


class TestTrimCutMarks:
    def test_manual_segments_accept_saved_type_field(self, tmp_path, monkeypatch):
        req = CutMarksSaveRequest(
            cut_indices=[2, 1],
            manual_segments=[
                {"start": "1.5", "end": "3.0", "type": "manual"},
                {"start": 4, "end": 4, "type": "manual"},
            ],
        )
        monkeypatch.setattr("webapp.routers.jobs_trim.get_job_dir", lambda _: tmp_path)

        result = save_cut_marks("test-job", req.cut_indices, req.manual_segments)
        saved_marks = json.loads((tmp_path / "captions.cut_marks.json").read_text(encoding="utf-8"))

        assert result["cut_indices"] == [1, 2]
        assert result["manual_segments"] == [{"start": 1.5, "end": 3.0, "type": "manual"}]
        assert saved_marks == [
            {"index": 1, "type": "caption"},
            {"index": 2, "type": "caption"},
            {"start": 1.5, "end": 3.0, "type": "manual"},
        ]


class TestTtsTrimmedInputs:
    def test_tts_prefers_trimmed_video_and_captions(self, tmp_path, monkeypatch):
        (tmp_path / "processed.trimmed.mp4").write_bytes(b"video")
        (tmp_path / "captions.trimmed.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\ntrimmed\n",
            encoding="utf-8",
        )
        job = SimpleNamespace(
            video_trimmed="processed.trimmed.mp4",
            captions_trimmed="captions.trimmed.srt",
            processed_video=str(tmp_path / "processed.mp4"),
        )
        monkeypatch.setattr("webapp.services.tts.load_job", lambda _: job)
        monkeypatch.setattr("webapp.services.tts.get_job_dir", lambda _: tmp_path)

        video_path, captions_path, source_stage = resolve_tts_input_paths("job")

        assert video_path == tmp_path / "processed.trimmed.mp4"
        assert captions_path == tmp_path / "captions.trimmed.srt"
        assert source_stage == "trimmed"

    def test_auto_tts_segments_prefer_trimmed_captions(self, tmp_path, monkeypatch):
        job = SimpleNamespace(
            video_trimmed="processed.trimmed.mp4",
            captions_trimmed_json="captions.trimmed.json",
            captions_trimmed="captions.trimmed.srt",
            tts_segments_json=None,
        )

        def fake_load_captions(_job_id, stage):
            if stage == "trimmed":
                return [Caption(1, 0.0, 1.0, "trimmed")]
            if stage == "working":
                return [Caption(1, 0.0, 5.0, "working")]
            return []

        saved_jobs = []
        monkeypatch.setattr("webapp.services.tts_segments.load_job", lambda _: job)
        monkeypatch.setattr("webapp.services.tts_segments.ensure_job_dir", lambda _: tmp_path)
        monkeypatch.setattr("webapp.services.tts_segments.load_captions", fake_load_captions)
        monkeypatch.setattr("webapp.services.tts_segments.get_tts_segments_json_path", lambda _: tmp_path / "tts.segments.json")
        monkeypatch.setattr("webapp.services.tts_segments.save_job", lambda saved: saved_jobs.append(saved))

        payload = build_and_store_tts_segments("job", segment_mode="none", stage="auto")

        assert payload["source_stage"] == "trimmed"
        assert payload["segments"][0]["text"].startswith("trimmed")


class TestJobManifest:
    def test_create_and_load(self, tmp_path):
        manifest = ensure_manifest(tmp_path, "test-job")
        assert manifest.job_id == "test-job"
        assert manifest.captions_version == 0
        loaded = JobManifest.load(tmp_path)
        assert loaded is not None
        assert loaded.job_id == "test-job"

    def test_invalidate_on_caption_change(self, tmp_path):
        manifest = ensure_manifest(tmp_path, "test-job")
        manifest.captions_version = 1
        manifest.trim_version = 1
        manifest.save(tmp_path)
        invalidate_derived_outputs(tmp_path)
        loaded = JobManifest.load(tmp_path)
        assert loaded.captions_version == 2
        assert loaded.trim_version == 0

    def test_staleness_detection(self, tmp_path):
        manifest = JobManifest(
            job_id="test",
            created_at="",
            updated_at="",
            captions_version=3,
            trim_version=2,
            tts_version=1,
        )
        assert manifest.is_stale("trim") is True
        assert manifest.is_stale("tts") is True
        manifest.trim_version = 3
        assert manifest.is_stale("trim") is False
