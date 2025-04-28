import os
import json
import pytest
import tempfile

# Add project root to allow importing 'src'
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from src.config import load_config, save_config # Import functions to test

# --- Fixtures ---

@pytest.fixture(scope="function") # Run for each test function
def temp_config_file():
    """Creates a temporary JSON config file for testing."""
    config_data = {
        "game_dir": "/fake/tf2/path",
        "log_level": "DEBUG",
        "admin_steamid": "12345",
        "ignored_users": ["BadUser1", "BadUser2"]
    }
    # Use NamedTemporaryFile to handle creation and cleanup
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json", encoding='utf-8') as tmp_file:
        json.dump(config_data, tmp_file, indent=2)
        file_path = tmp_file.name
    # print(f"DEBUG: Created temp config file: {file_path}") # For debugging tests
    yield file_path # Provide the path to the test function
    # Cleanup: file is automatically deleted when 'with' block exits if delete=True (default)
    # If delete=False, we need manual cleanup:
    # print(f"DEBUG: Cleaning up temp config file: {file_path}") # For debugging tests
    os.remove(file_path)


@pytest.fixture(scope="function")
def non_existent_config_path():
    """Provides a path that definitely does not exist."""
    # Use tempfile directory but ensure file doesn't exist
    path = os.path.join(tempfile.gettempdir(), "non_existent_config_test.json")
    if os.path.exists(path):
        os.remove(path) # Ensure it's gone before test
    yield path
    # No cleanup needed as file shouldn't exist


@pytest.fixture(scope="function")
def invalid_json_file():
    """Creates a temporary file with invalid JSON content."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json", encoding='utf-8') as tmp_file:
        tmp_file.write("{invalid json content,}")
        file_path = tmp_file.name
    yield file_path
    os.remove(file_path)

# --- Test Cases ---

def test_load_config_success(temp_config_file):
    """Test loading a valid configuration file."""
    config = load_config(temp_config_file)
    assert isinstance(config, dict)
    assert config["game_dir"] == "/fake/tf2/path"
    assert config["log_level"] == "DEBUG"
    assert config["admin_steamid"] == "12345"
    assert isinstance(config["ignored_users"], list)
    assert len(config["ignored_users"]) == 2
    assert "BadUser1" in config["ignored_users"]

def test_load_config_file_not_found(non_existent_config_path, caplog):
    """Test loading when the config file does not exist."""
    # caplog is a pytest fixture to capture log output
    import logging
    caplog.set_level(logging.ERROR) # Capture ERROR level messages

    config = load_config(non_existent_config_path)
    assert config == {} # Should return empty dict on failure
    # Check if the error was logged
    assert f"Configuration file not found: {non_existent_config_path}" in caplog.text

def test_load_config_invalid_json(invalid_json_file, caplog):
    """Test loading a file with invalid JSON content."""
    import logging
    caplog.set_level(logging.ERROR)

    config = load_config(invalid_json_file)
    assert config == {}
    assert f"Error decoding JSON configuration file {invalid_json_file}" in caplog.text

def test_save_config_success():
    """Test saving a configuration dictionary to a file."""
    save_data = {"setting1": "value1", "setting2": 123, "nested": {"a": True}}
    # Use a temporary directory for the saved file
    with tempfile.TemporaryDirectory() as tmp_dir:
        save_path = os.path.join(tmp_dir, "saved_config.json")
        save_config(save_data, save_path)

        # Verify file was created
        assert os.path.exists(save_path)

        # Verify content by reloading
        reloaded_data = load_config(save_path)
        assert reloaded_data == save_data

def test_save_config_creates_directory():
    """Test if save_config creates the directory if it doesn't exist."""
    save_data = {"test": "data"}
    with tempfile.TemporaryDirectory() as tmp_base_dir:
        # Create a path with a non-existent subdirectory
        non_existent_subdir = os.path.join(tmp_base_dir, "new_subdir")
        save_path = os.path.join(non_existent_subdir, "config.json")

        assert not os.path.exists(non_existent_subdir) # Ensure subdir doesn't exist yet
        save_config(save_data, save_path)
        assert os.path.exists(save_path) # Check if file was created (implies dir was created)

        # Verify content
        reloaded_data = load_config(save_path)
        assert reloaded_data == save_data