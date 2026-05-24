import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
import yaml
import json


class SourceConfig(BaseModel):
    local: str
    remote: str
    exclude: List[str] = Field(default_factory=list)
    include: List[str] = Field(default_factory=list)
    recursive: bool = True
    delete_after_backup: bool = False


class RetryConfig(BaseModel):
    max_retries: int = 3
    retry_delay: int = 10


class ConcurrencyConfig(BaseModel):
    max_upload_workers: int = 3


class AppConfig(BaseModel):
    sources: List[SourceConfig]
    schedule: str = "每天 02:00"
    schedule_enabled: bool = True
    remote_root: str = "/自动备份"
    retry: RetryConfig = Field(default_factory=RetryConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    log_level: str = "INFO"

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AppConfig":
        if path is None:
            path = os.environ.get(
                "QUARK_CONFIG",
                str(Path.cwd() / "config.yaml")
            )
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def save_cache(self, cache: dict, name: str = "backup_cache"):
        cache_dir = Path.cwd() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{name}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return cache_file

    def load_cache(self, name: str = "backup_cache") -> dict:
        cache_file = Path.cwd() / "cache" / f"{name}.json"
        if not cache_file.exists():
            return {}
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
