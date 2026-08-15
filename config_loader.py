import json
import os
import sys
from pathlib import Path

import config_registry as cfg


def _resolve_config_path(base_dir, config_path):
    default_config_path = config_path or base_dir / "config.json"
    resolved = Path(os.getenv("SCRAPER_CONFIG", default_config_path))
    if not resolved.is_absolute():
        resolved = base_dir / resolved
    return resolved


def _read_json_object(path):
    with open(path, "r", encoding="utf-8") as handle:
        try:
            loaded = json.load(handle) or {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in config file {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        print(
            f"Warning: config file {path} does not contain a JSON object; "
            f"ignoring its contents.",
            file=sys.stderr,
        )
        return {}
    return loaded


def _apply_env_value(field, raw):
    if field.coerce is None:
        return raw
    try:
        return field.coerce(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid value for '{field.name}' from environment: {raw!r} ({exc})"
        ) from exc


def load_config(base_dir=None, config_path=None):
    """Load config from config.json (or SCRAPER_CONFIG) plus the environment.

    Field names, defaults, secrecy, required-ness, and env var names all
    come from `config_registry` - this function only orchestrates reading
    the file and the environment, it holds no config knowledge itself.
    """
    base_dir = Path(base_dir or Path(__file__).resolve().parent)
    config = dict(cfg.defaults())

    resolved_config_path = _resolve_config_path(base_dir, config_path)
    if resolved_config_path.exists():
        loaded = _read_json_object(resolved_config_path)
        cfg.validate_file_payload(loaded.keys())
        config.update(loaded)

    for field in cfg.env_sourced_fields():
        for env_var in field.env_vars:
            raw = os.getenv(env_var)
            if raw:
                config[field.name] = _apply_env_value(field, raw)
                break

    missing = [f.name for f in cfg.required_fields() if not config.get(f.name)]
    if missing:
        raise ValueError(f"Missing required config value(s): {', '.join(missing)}")

    return config
