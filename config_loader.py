import json
import os
import sys
from pathlib import Path


def load_config(base_dir=None, config_path=None, defaults=None, env_overrides=None):
    base_dir = Path(base_dir or Path(__file__).resolve().parent)
    default_config_path = config_path or base_dir / "config.json"

    if defaults is None:
        defaults = {}

    config = dict(defaults)

    resolved_config_path = Path(os.getenv("SCRAPER_CONFIG", default_config_path))
    if not resolved_config_path.is_absolute():
        resolved_config_path = base_dir / resolved_config_path

    if resolved_config_path.exists():
        with open(resolved_config_path, "r", encoding="utf-8") as handle:
            try:
                loaded = json.load(handle) or {}
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in config file {resolved_config_path}: {exc}"
                ) from exc

        if isinstance(loaded, dict):
            config.update(loaded)
        else:
            print(
                f"Warning: config file {resolved_config_path} does not contain a "
                f"JSON object; ignoring its contents.",
                file=sys.stderr,
            )

    if env_overrides:
        for key, env_name in env_overrides.items():
            value = os.getenv(env_name)
            if value is None or value == "":
                continue

            default_value = defaults.get(key)
            if isinstance(default_value, bool):
                config[key] = value.strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(default_value, int):
                try:
                    config[key] = int(value)
                except ValueError:
                    raise ValueError(
                        f"Environment variable {env_name}={value!r} must be an "
                        f"integer for config key '{key}'."
                    )
            else:
                config[key] = value

    return config