from utils.config_manager import ConfigManager

def main():
    cfg = ConfigManager()

    config = cfg.load_config("pressure_controller")

    print(config)
    config = cfg.load_config("valves")
    print(config)

    config = cfg.get_all_configs()

    print(config)

if __name__ == "__main__":
    main()