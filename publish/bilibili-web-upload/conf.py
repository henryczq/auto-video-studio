"""Bilibili Web Upload Configuration."""

from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

# Chrome浏览器设置
LOCAL_CHROME_PATH = ""  # 可选，设置本地Chrome路径，如 "C:/Program Files/Google/Chrome/Application/chrome.exe"
HEADLESS = True  # 是否无头模式运行

# Cookie保存路径
COOKIE_DIR = BASE_DIR / "cookies"
COOKIE_FILE = COOKIE_DIR / "bilibili_web_uploader" / "account.json"

# 日志配置
LOG_DIR = BASE_DIR / "logs"

# 视频目录
VIDEO_DIR = BASE_DIR / "videos"

# 默认上传设置
DEFAULT_CATEGORY = "vlog"  # 默认分区
DEFAULT_COPYRIGHT = 1  # 1=自制, 2=转载
