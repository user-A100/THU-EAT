"""配置管理：学号、校园卡 cookie 等存于本地 data/config.json。"""
import json
import os
import sys
from pathlib import Path

# PyInstaller 打包后 __file__ 指向临时解压目录，数据需持久化到 EXE 同目录
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(os.path.dirname(sys.executable))
else:
    BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "eat_stat.db"

# 程序版本号：发布 Release 时同步更新，Release tag 为 v+VERSION（如 v1.0.0）
VERSION = "1.0.0"

# 配置字段
DEFAULT_CONFIG = {
    "idserial": "",          # 学号
    "servicehall": "",       # card.tsinghua.edu.cn 的 servicehall cookie 值
    "last_sync_date": "",    # 上次成功同步到的最晚日期（YYYY-MM-DD）
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """读取配置，缺失字段用默认值补齐。"""
    ensure_dirs()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> dict:
    """保存配置（仅写入已知字段），返回清洗后的配置。"""
    ensure_dirs()
    clean = {k: cfg.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return clean


def mask_cookie(value: str) -> str:
    """cookie 脱敏，用于回显给前端。"""
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]
