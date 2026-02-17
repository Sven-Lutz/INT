from __future__ import annotations

import copy
import logging
import os
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _set_by_dotpath(d: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _get_by_dotpath(d: Dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    cur: Any = d
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            raise KeyError(path)
        cur = cur[p]
    return cur


class ConfigManager:
    """
    Loads YAML configs from:
      - defaults: src/config/defaults/<name>.yaml
      - runtime : src/config/runtime/<name>.yaml  (bootstrapped from defaults if missing)

    Merging rule:
      merged = deep_merge(general.yaml, specific.yaml)

    Overrides:
      - if env var PELLIKAN_CONFIG_DIR is set, it overrides runtime dir
      - if ConfigManager(config_dir=...) is passed, it overrides runtime dir
    """

    _instance: Optional["ConfigManager"] = None

    def __new__(cls, config_dir: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init(config_dir)
            return cls._instance

        # IMPORTANT: if caller passes a config_dir later, honor it
        if config_dir is not None:
            new_dir = os.path.abspath(str(config_dir))
            if os.path.abspath(cls._instance.runtime_dir) != new_dir:
                logger.info("ConfigManager: reinitializing with new config_dir=%s", new_dir)
                cls._instance._init(config_dir)

        return cls._instance

    def _init(self, config_dir: Optional[str]) -> None:
        base = os.path.dirname(os.path.dirname(__file__))  # .../src

        # defaults are always inside repo
        self.defaults_dir = os.path.abspath(os.path.join(base, "config", "defaults"))

        # runtime can be overridden
        env_dir = os.environ.get("PELLIKAN_CONFIG_DIR")
        runtime = env_dir or config_dir or os.path.join(base, "config", "runtime")
        self.runtime_dir = os.path.abspath(runtime)

        # kept for compatibility (some code might read config_dir)
        self.config_dir = self.runtime_dir

        os.makedirs(self.runtime_dir, exist_ok=True)

        self._cache: Dict[str, Dict[str, Any]] = {}
        self._general: Dict[str, Any] = {}

        logger.info("ConfigManager initialized")
        logger.info("runtime_dir=%s", self.runtime_dir)
        logger.info("defaults_dir=%s", self.defaults_dir)

        self._load_general()

    def _runtime_path(self, name: str) -> str:
        return os.path.join(self.runtime_dir, f"{name}.yaml")

    def _defaults_path(self, name: str) -> str:
        return os.path.join(self.defaults_dir, f"{name}.yaml")

    def _ensure_runtime_from_defaults(self, name: str) -> None:
        runtime_path = self._runtime_path(name)
        if os.path.exists(runtime_path):
            return

        defaults_path = self._defaults_path(name)
        if not os.path.exists(defaults_path):
            return

        logger.info("Bootstrapping runtime config '%s' from defaults", name)
        data = self._read_yaml(defaults_path)
        self._write_yaml(runtime_path, data)

    def _read_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if not isinstance(data, dict):
            raise ValueError(f"YAML root must be a mapping: {path}")

        return data

    def _write_yaml(self, path: str, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not isinstance(data, dict):
            raise ValueError("Config data must be a dict.")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)

    def _load_general(self) -> None:
        self._ensure_runtime_from_defaults("general")
        path = self._runtime_path("general")

        if not os.path.exists(path):
            logger.info("general.yaml not found — using empty defaults.")
            self._general = {}
            return

        self._general = self._read_yaml(path)

    def reload_general(self) -> None:
        self._load_general()
        self._cache.clear()

    def load_config(self, name: str, *, use_cache: bool = True) -> Dict[str, Any]:
        if use_cache and name in self._cache:
            return copy.deepcopy(self._cache[name])

        self._ensure_runtime_from_defaults(name)
        specific = self._read_yaml(self._runtime_path(name))
        merged = _deep_merge(copy.deepcopy(self._general), specific)

        self._cache[name] = merged
        return copy.deepcopy(merged)

    def save_config(self, name: str, data: Dict[str, Any]) -> None:
        self._write_yaml(self._runtime_path(name), data)
        self._cache.pop(name, None)

    def update_config(self, name: str, key: str, value: Any) -> None:
        self._ensure_runtime_from_defaults(name)
        path = self._runtime_path(name)
        data = self._read_yaml(path)

        if "." in key:
            _set_by_dotpath(data, key, value)
        else:
            data[key] = value

        self._write_yaml(path, data)
        self._cache.pop(name, None)

    def get(self, name: str, key: str, default: Any = None) -> Any:
        cfg = self.load_config(name)
        try:
            if "." in key:
                return _get_by_dotpath(cfg, key)
            return cfg[key]
        except KeyError:
            return default

    def invalidate(self, name: Optional[str] = None) -> None:
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    def get_all_loaded(self) -> Dict[str, Dict[str, Any]]:
        return copy.deepcopy(self._cache)
