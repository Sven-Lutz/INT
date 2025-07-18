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


        general_path = os.path.join(self.config_dir, "general.yaml")
        if os.path.exists(general_path):
            logger.info("loading general.yaml")
            with open(general_path, "r") as f:
                self.general_config = yaml.safe_load(f)
        else:
            logger.info("loading empty general.yaml")
            self.general_config = {}

    def load_config(self, name):
        if name in self._configs:
            return self._configs[name]

        path = os.path.join(self.config_dir, f"{name}.yaml")
        if not os.path.exists(path):
            logger.error(f"Config file {name}.yaml not found in {self.config_dir}")
            raise FileNotFoundError(f"Config file {name}.yaml not found in {self.config_dir}")

        with open(path, "r") as f:
            logger.info(f"loading {name}.yaml")
            specific_cfg = yaml.safe_load(f) or {}

        # Merge general config into specific config, without modifying originals
        merged_cfg = copy.deepcopy(self.general_config)
        merged_cfg.update(specific_cfg)

        self._configs[name] = merged_cfg
        return merged_cfg

    def get_all_configs(self):
        # Return all loaded configs (only those actually loaded)
        return dict(self._configs)