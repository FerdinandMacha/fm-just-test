"""Single source of truth for the scraper's configuration fields.

Every setting the app can read is declared here exactly once, via
`register()`. That one declaration decides everything about the field:
its default, whether it's a secret (and therefore forbidden from
config.json), whether it's required, and which environment variable(s)
can supply it.

`config_loader.py` never hard-codes a field name, default, or env var -
it only asks this module. Adding or removing a setting means editing
this file in exactly one place.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class ConfigField:
    name: str
    default: Any
    secret: bool = False
    required: bool = False
    env_vars: Tuple[str, ...] = ()
    coerce: Optional[Callable[[str], Any]] = None


_REGISTRY: Dict[str, ConfigField] = {}


def register(
    name: str,
    default: Any,
    *,
    secret: bool = False,
    required: bool = False,
    env_vars: Optional[Iterable[str]] = None,
    coerce: Optional[Callable[[str], Any]] = None,
) -> None:
    """Declare one config field. Call once per field, at import time.

    env_vars controls where this field's value can come from besides the
    config file:
      - omitted (None): defaults to the field's name upper-cased, e.g.
        "smtp_host" -> "SMTP_HOST". This is the common case.
      - an explicit tuple: use this when the env var name doesn't match
        the field name, or when more than one name should be tried, in
        order - the first one set to a non-empty value wins. This is how
        a field can have both its normal name (e.g. SMTP_PASSWORD) and a
        production alias (e.g. GMAIL_PASSWORD) that takes priority.
      - () (explicit empty tuple): this field cannot be set via the
        environment at all - only the config file or the default apply.
    """
    if name in _REGISTRY:
        raise ValueError(f"Config field {name!r} is already registered")
    if env_vars is None:
        env_vars = (name.upper(),)
    _REGISTRY[name] = ConfigField(
        name=name,
        default=default,
        secret=secret,
        required=required,
        env_vars=tuple(env_vars),
        coerce=coerce,
    )


def unregister(name: str) -> None:
    """Retire a field. No-op if it isn't registered."""
    _REGISTRY.pop(name, None)


def reset() -> None:
    """Clear the registry. Mainly useful for tests."""
    _REGISTRY.clear()


def all_fields() -> List[ConfigField]:
    return list(_REGISTRY.values())


def defaults() -> Dict[str, Any]:
    return {f.name: f.default for f in _REGISTRY.values()}


def public_names() -> FrozenSet[str]:
    """Names a config file is allowed to set."""
    return frozenset(f.name for f in _REGISTRY.values() if not f.secret)


def env_sourced_fields() -> List[ConfigField]:
    """Fields that can be supplied or overridden via an environment variable."""
    return [f for f in _REGISTRY.values() if f.env_vars]


def required_fields() -> List[ConfigField]:
    return [f for f in _REGISTRY.values() if f.required]


def unknown_keys(keys: Iterable[str]) -> List[str]:
    """Keys in a config file that aren't registered anywhere - typos or
    unrelated data that has no business being there."""
    return sorted(k for k in keys if k not in _REGISTRY)


def disallowed_secret_keys(keys: Iterable[str]) -> List[str]:
    """Registered keys that are secret - never allowed in a file."""
    return sorted(k for k in keys if k in _REGISTRY and _REGISTRY[k].secret)


def validate_file_payload(keys: Iterable[str]) -> None:
    """Raise if `keys` contains anything a config file must not hold.

    This is an allowlist check, not a denylist: any key that isn't a
    known, non-secret field is rejected, regardless of its name or
    casing. That's what stops both typos and secrets pasted under an
    unregistered key from silently sitting in the file.
    """
    keys = list(keys)
    problems = []
    unknown = unknown_keys(keys)
    if unknown:
        problems.append(f"unregistered field(s): {', '.join(unknown)}")
    leaked = disallowed_secret_keys(keys)
    if leaked:
        problems.append(
            f"secret field(s) that must not be stored in a file: {', '.join(leaked)}"
        )
    if problems:
        raise ValueError("Invalid config file - " + "; ".join(problems))
