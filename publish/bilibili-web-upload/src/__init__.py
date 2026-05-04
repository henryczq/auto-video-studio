"""Bilibili web upload package.

Keep imports lazy so the Playwright web uploader can run in the lighter
social-auto-upload environment without loading API-only dependencies.
"""

__all__ = [
    "BilibiliAuth",
    "HotMonitor",
    "BilibiliDownloader",
    "BilibiliWatcher",
    "SubtitleDownloader",
    "BilibiliPlayer",
    "BilibiliPublisher",
    "WebUploader",
    "extract_bvid",
]


def __getattr__(name):
    if name == "BilibiliAuth":
        from src.auth import BilibiliAuth
        return BilibiliAuth
    if name == "HotMonitor":
        from src.hot_monitor import HotMonitor
        return HotMonitor
    if name == "BilibiliDownloader":
        from src.downloader import BilibiliDownloader
        return BilibiliDownloader
    if name == "BilibiliWatcher":
        from src.watcher import BilibiliWatcher
        return BilibiliWatcher
    if name == "SubtitleDownloader":
        from src.subtitle import SubtitleDownloader
        return SubtitleDownloader
    if name == "BilibiliPlayer":
        from src.player import BilibiliPlayer
        return BilibiliPlayer
    if name == "BilibiliPublisher":
        from src.publisher import BilibiliPublisher
        return BilibiliPublisher
    if name == "WebUploader":
        from src.web_uploader import BilibiliWebVideo
        return BilibiliWebVideo
    if name == "extract_bvid":
        from src.utils import extract_bvid
        return extract_bvid
    raise AttributeError(name)
