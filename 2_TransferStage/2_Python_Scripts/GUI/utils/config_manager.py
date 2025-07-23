import os
import yaml
import logging
import copy

logger = logging.getLogger(__name__)                             # Create a logger for this module

class ConfigManager:
    """
        Singleton for static configuration management.

        This class handles reading and caching YAML config files.
        Runtime metadata should be managed separately via MetadataManager.
    """

    _instance = None

    def __new__(cls, config_dir=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init(config_dir)
        return cls._instance

    def _init(self, config_dir):
        self.config_dir = config_dir or os.path.join(os.getcwd(), "configs")
        self._configs = {}
        self.general_config = None
        self._load_general_config()

    def _load_general_config(self):
        self.load_config("general")
        self.general_config = self._configs["general"]
        return

    def load_config(self, name):
        if name in self._configs:
            return self._configs[name]

        path = os.path.join(self.config_dir, f"{name}.yaml")
        default_path = os.path.join(self.config_dir, f"{name}_default.yaml")
        if not os.path.exists(path):
            if os.path.exists(default_path):
                logger.warning(f"{name}.yaml not found. Falling back to {name}_default.yaml.")
                with open(default_path, "r") as f:
                    default_cfg = yaml.safe_load(f) or {}

                # Save default as actual config
                with open(path, "w") as f:
                    yaml.safe_dump(default_cfg, f)
                logger.info(f"Saved fallback default config as {name}.yaml.")
            else:
                logger.error(f"Neither {name}.yaml nor {name}_default.yaml found in {self.config_dir}")
                raise FileNotFoundError(f"Missing both config and default for '{name}'")

        with open(path, "r") as f:
            logger.info(f"loading {name}.yaml")
            specific_cfg = yaml.safe_load(f) or {}

        if name is not "general":
            # Merge general config into specific config, without modifying originals
            merged_cfg = copy.deepcopy(self.general_config)
            merged_cfg.update(specific_cfg)
        else:
            merged_cfg = specific_cfg

        self._configs[name] = merged_cfg
        return merged_cfg

    def get_all_configs(self):
        # Return all loaded configs (only those actually loaded)
        return dict(self._configs)

    def update_config(self, name, key, value, save=False):
        if name not in self._configs:
            logger.error(f"Config '{name}' not loaded. Cannot update.")
            return

        config = self._configs[name]
        config[key] = value
        logger.info(f"Updated '{key}' in config '{name}' to: {value}")

        if save:
            self.save_config(name)
        return

    def save_config(self, name):
        if name not in self._configs:
            logger.error(f"Cannot save. Config '{name}' not loaded.")
            return

        path = os.path.join(self.config_dir, f"{name}.yaml")
        to_save = self._configs[name]

        try:
            with open(path, "w") as f:
                yaml.safe_dump(to_save, f)
            logger.info(f"Saved config '{name}' to disk.")
        except Exception as e:
            logger.error(f"Failed to save config '{name}': {e}")
        return