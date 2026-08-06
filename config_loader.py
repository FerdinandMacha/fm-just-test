import json
import os
from pathlib import Path


def load_config(base_dir=None, config_path=None, defaults=None, env_overrides=None):
    base_dir = Path(base_dir or Path(__file__).resolve().parent)
    default_config_path = config_path or base_dir / "config.json"

    if defaults is None:
        defaults = {}

    config = dict(defaults)

    config_path = Path(os.getenv("SCRAPER_CONFIG", default_config_path))
    if not config_path.is_absolute():
        config_path = base_dir / config_path

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as handle:
            try:
                loaded = json.load(handle) or {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in config file {config_path}: {exc}") from exc

            if isinstance(loaded, dict):
                config.update(loaded)

    if env_overrides:
        for key, env_name in env_overrides.items():
            value = os.getenv(env_name)
            if value is not None and value != "":
                config[key] = value

    return config
