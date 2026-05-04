"""Caption transformation - apply terms, adjust timing, merge/split captions."""

import re
from typing import List, Dict, Callable, Optional


class CaptionTransform:
    """Transform captions with various operations."""

    def apply_terms(self, captions: List[dict], terms: Dict[str, str]) -> List[dict]:
        result = []
        for cap in captions:
            text = cap["text"]
            for src, dst in terms.items():
                text = text.replace(src, dst)
            result.append({**cap, "text": text})
        return result

    def apply_regex_terms(self, captions: List[dict], terms: Dict[str, str]) -> List[dict]:
        result = []
        for cap in captions:
            text = cap["text"]
            for pattern, replacement in terms.items():
                try:
                    text = re.sub(pattern, replacement, text)
                except re.error:
                    continue
            result.append({**cap, "text": text})
        return result

    def adjust_timing(self, captions: List[dict], offset: float,
                      trim_start: Optional[float] = None,
                      trim_end: Optional[float] = None) -> List[dict]:
        result = []
        for cap in captions:
            start = max(0, cap["start"] + offset)
            end = cap["end"] + offset
            if trim_start is not None:
                if end <= trim_start:
                    continue
                start = max(start, trim_start)
            if trim_end is not None:
                if start >= trim_end:
                    continue
                end = min(end, trim_end)
            result.append({**cap, "start": start, "end": end})
        return result

    def filter_by_time_range(self, captions: List[dict],
                             start: Optional[float] = None,
                             end: Optional[float] = None) -> List[dict]:
        result = []
        for cap in captions:
            if start is not None and cap["end"] < start:
                continue
            if end is not None and cap["start"] > end:
                continue
            result.append(cap)
        return result

    def merge_adjacent(self, captions: List[dict], gap_threshold: float = 0.5) -> List[dict]:
        if not captions:
            return []
        result = [dict(captions[0])]
        for cap in captions[1:]:
            last = result[-1]
            if cap["start"] - last["end"] <= gap_threshold:
                last["end"] = cap["end"]
                if cap["text"]:
                    last["text"] = last["text"] + " " + cap["text"]
            else:
                result.append(dict(cap))
        return result

    def split_by_gaps(self, captions: List[dict], gap_threshold: float = 3.0) -> List[List[dict]]:
        if not captions:
            return []
        groups = []
        current_group = [dict(captions[0])]
        for cap in captions[1:]:
            last = current_group[-1]
            if cap["start"] - last["end"] <= gap_threshold:
                current_group.append(dict(cap))
            else:
                groups.append(current_group)
                current_group = [dict(cap)]
        groups.append(current_group)
        return groups

    def expand_to_words(self, captions: List[dict], words: List[dict]) -> List[dict]:
        if not captions or not words:
            return captions
        result = []
        for cap in captions:
            cap_words = [w for w in words if w.get("start", -1) >= cap["start"] and w.get("end", -1) <= cap["end"]]
            if cap_words:
                result.append({**cap, "words": cap_words})
            else:
                result.append(cap)
        return result

    def find_similar(self, text: str, candidates: List[str], threshold: float = 0.8) -> List[tuple]:
        results = []
        text_lower = text.lower()
        for candidate in candidates:
            similarity = self._jaccard_similarity(text_lower, candidate.lower())
            if similarity >= threshold:
                results.append((candidate, similarity))
        return sorted(results, key=lambda x: -x[1])

    def _jaccard_similarity(self, s1: str, s2: str) -> float:
        set1 = set(s1.split())
        set2 = set(s2.split())
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0


caption_transform = CaptionTransform()
