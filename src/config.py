import json
import os
import logging

DEFAULT_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config.json'))

def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Loads configuration from a JSON file.

    Args:
        config_path: Path to the configuration file.

    Returns:
        A dictionary containing the configuration settings.
        Returns an empty dict if the file doesn't exist or is invalid.
    """
    if not os.path.exists(config_path):
        logging.error(f"Configuration file not found: {config_path}")
        # Optionally create a default config here if needed
        # save_config({}, config_path) # Example
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            logging.info(f"Configuration loaded successfully from {config_path}")
            return config_data
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON configuration file {config_path}: {e}")
        return {}
    except IOError as e:
        logging.error(f"Error reading configuration file {config_path}: {e}")
        return {}

def save_config(config_data: dict, config_path: str = DEFAULT_CONFIG_PATH):
    """Saves configuration data to a JSON file.

    Args:
        config_data: The configuration dictionary to save.
        config_path: Path to the configuration file.
    """
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
            logging.info(f"Configuration saved successfully to {config_path}")
    except IOError as e:
        logging.error(f"Error writing configuration file {config_path}: {e}")
    except TypeError as e:
        logging.error(f"Error serializing configuration data to JSON: {e}")

# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    # Set up basic logging for testing this module directly
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Test loading
    loaded_settings = load_config()
    print("Loaded Config:", loaded_settings)

    # Test saving (optional - uncomment to test)
    # loaded_settings['new_setting'] = 'test_value'
    # save_config(loaded_settings)
    # print("Saved updated config.")
    # reloaded_settings = load_config()
    # print("Reloaded Config:", reloaded_settings)