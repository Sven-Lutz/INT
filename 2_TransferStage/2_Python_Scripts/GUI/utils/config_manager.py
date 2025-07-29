import os
import yaml
import logging
import copy

logger = logging.getLogger(__name__)                                                # Create a logger for this module

class ConfigManager:
    """
        Singleton for static configuration management.

        This class handles reading and caching YAML config files.
        Runtime metadata should be managed separately via MetadataManager.
    """
    ###############################
    ###Handling of the singleton###
    ###############################
    _instance = None                                                                # Class-level variable to hold the singleton instance

    def __new__(cls):
        """Override __new__ to enforce singleton pattern"""
        if cls._instance is None:                                                   # If no instance exists
            cls._instance = super().__new__(cls)                                    # create a new instance
            cls._instance._init()                                                   # and initialize
        return cls._instance                                                        # Return singleton instance

    def _init(self):
        """Custom initializer to allow singleton pattern"""
        self.config_dir = os.path.join(os.getcwd(), "configs")                      # get config path
        self._configs = {}                                                          # create an empty dict to handle multiple configs
        self.general_config = None
        self._load_general_config()                                                 # load general config in the beginning of the singleton
        return

    def _load_general_config(self):
        """Load general config"""
        self.load_config("general")                                                 # load general config
        self.general_config = self._configs["general"]                              # add general config to the config dict
        self._check_project_path()
        return

    def _check_project_path(self):
        if self.general_config.get("Project Path") != os.getcwd():
            self.update_config("general", "Project Path", os.getcwd(), True)
            logger.info("Project Path has been updated")
        return

    def load_config(self, name):
        """
        def: Loads config of name and checks if it needs to load the default version. Creates a copy of name_default.yaml in name.yaml
        params: name: String which indicates which config needs to be loaded
        return: merged_cfg: dict which is a combination of name.yaml and general.yaml, if general.yaml is loaded then no mergin takes place
        """

        if name in self._configs:                                                                               # If already loaded return from cache
            return self._configs[name]

        path = os.path.join(self.config_dir, f"{name}.yaml")                                                    # path of name.yaml
        default_path = os.path.join(self.config_dir, "defaults", f"{name}_default.yaml")                                    # path of name_default.yaml
        if not os.path.exists(path):                                                                            # check if default needs to be loaded
            if os.path.exists(default_path):                                                                    # check if default can be loaded
                logger.warning(f"{name}.yaml not found. Falling back to {name}_default.yaml.")
                with open(default_path, "r") as f:
                    default_cfg = yaml.safe_load(f) or {}                                                       # load default
                    specific_cfg = default_cfg                                                                  # and set default config as actual default

                with open(path, "w") as f:
                    yaml.safe_dump(default_cfg, f)                                                              # save default as actual config
                logger.info(f"Saved fallback default config as {name}.yaml.")
            else:
                logger.error(f"Neither {name}.yaml nor {name}_default.yaml found in {self.config_dir}")         # return error if both files are missing
                raise FileNotFoundError(f"Missing both config and default for '{name}'")
        else:
            with open(path, "r") as f:
                logger.info(f"loading {name}.yaml")
                specific_cfg = yaml.safe_load(f) or {}                                      # load name.yaml

        if name != "general":
            merged_cfg = copy.deepcopy(specific_cfg)                                        # Merge general config into specific config, without modifying originals
            merged_cfg["Project Path"] = self.general_config["Project Path"]
            merged_cfg["Config Path"] = self.config_dir
            merged_cfg.update(specific_cfg)
        else:
            merged_cfg = specific_cfg                                                       # do not merge if name is general
        self._configs[name] = merged_cfg                                                    # load merged_cfg in config dict
        return merged_cfg                                                                   # return merged config

    def get_all_configs(self):
        """Return all loaded configs (only those actually loaded)"""
        return dict(self._configs)

    def update_config(self, name, key, value, save=True):
        """
        Updates the (possibly nested) key of the name.yaml with value and optionally saves it.

        Parameters:
            name (str): Name of the config to update.
            key (str): Dot-separated key string (e.g., "database.host").
            value (Any): New value to assign to the key.
            save (bool): Whether to persist changes to the file.

        Returns:
            None
        """
        if name not in self._configs:
            logger.error(f"Config '{name}' not loaded. Cannot update.")
            return

        config = self._configs[name]
        keys = key.split(".")
        sub_config = config
        for k in keys[:-1]:
            if k not in sub_config or not isinstance(sub_config[k], dict):
                sub_config[k] = {}  # Auto-create nested dicts if missing
            sub_config = sub_config[k]

        sub_config[keys[-1]] = value
        logger.info(f"Updated '{key}' in config '{name}' to: {value}")
        self._configs[name] = config

        if name == "general":
            self._load_general_config()
        if save:
            self.save_config(name)

    def save_config(self, name):
        """
        def: Saves the config to name.yaml
        params: name: String which indicates which config needs to be changed
        return: ---
        """
        if name not in self._configs:                                           # if the config has not been loaded it cannot be saved
            logger.error(f"Cannot save. Config '{name}' not loaded.")
            return

        path = os.path.join(self.config_dir, f"{name}.yaml")                    # set the path of the file
        to_save = self._configs[name]                                           # get config to be saved

        try:
            with open(path, "w") as f:
                yaml.safe_dump(to_save, f)                                      # save config to file
            logger.info(f"Saved config '{name}' to disk.")
        except Exception as e:
            logger.error(f"Failed to save config '{name}': {e}")
        return

