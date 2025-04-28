import os
import json
import pytest
import tempfile

# add project root to allow importing 'src'
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from src.config import load_config, save_config # import functions to test

# --- fixtures ---

@pytest.fixture(scope="function") # run for each test function
def temp_config_file():
    """creates a temporary json config file for testing."""
    config_data = {
        "game_dir": "/fake/tf2/path",
        "log_level": "DEBUG",
        "admin_steamid": "12345",
        "ignored_users": ["BadUser1", "BadUser2"]
    }
    # use namedtemporaryfile to handle creation and cleanup
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json", encoding='utf-8') as tmp_file:
        json.dump(config_data, tmp_file, indent=2)
        file_path = tmp_file.name
    # print(f"debug: created temp config file: {file_path}") # for debugging tests
    yield file_path # provide the path to the test function
    # cleanup: file is automatically deleted when 'with' block exits if delete=true (default)
    # if delete=false, we need manual cleanup:
    # print(f"debug: cleaning up temp config file: {file_path}") # for debugging tests
    os.remove(file_path)


@pytest.fixture(scope="function")
def non_existent_config_path():
    """provides a path that definitely does not exist."""
    # use tempfile directory but ensure file doesn't exist
    path = os.path.join(tempfile.gettempdir(), "non_existent_config_test.json")
    if os.path.exists(path):
        os.remove(path) # ensure it's gone before test
    yield path
    # no cleanup needed as file shouldn't exist


@pytest.fixture(scope="function")
def invalid_json_file():
    """creates a temporary file with invalid json content."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json", encoding='utf-8') as tmp_file:
        tmp_file.write("{invalid json content,}")
        file_path = tmp_file.name
    yield file_path
    os.remove(file_path)

# --- test cases ---

def test_load_config_success(temp_config_file):
    """test loading a valid configuration file."""
    config = load_config(temp_config_file)
    assert isinstance(config, dict)
    assert config["game_dir"] == "/fake/tf2/path"
    assert config["log_level"] == "DEBUG"
    assert config["admin_steamid"] == "12345"
    assert isinstance(config["ignored_users"], list)
    assert len(config["ignored_users"]) == 2
    assert "BadUser1" in config["ignored_users"]

def test_load_config_file_not_found(non_existent_config_path, caplog):
    """test loading when the config file does not exist."""
    # caplog is a pytest fixture to capture log output
    import logging
    caplog.set_level(logging.ERROR) # capture error level messages

    config = load_config(non_existent_config_path)
    assert config == {} # should return empty dict on failure
    # check if the error was logged
    assert f"Configuration file not found: {non_existent_config_path}" in caplog.text

def test_load_config_invalid_json(invalid_json_file, caplog):
    """test loading a file with invalid json content."""
    import logging
    caplog.set_level(logging.ERROR)

    config = load_config(invalid_json_file)
    assert config == {}
    assert f"Error decoding JSON configuration file {invalid_json_file}" in caplog.text

def test_save_config_success():
    """test saving a configuration dictionary to a file."""
    save_data = {"setting1": "value1", "setting2": 123, "nested": {"a": True}}
    # use a temporary directory for the saved file
    with tempfile.TemporaryDirectory() as tmp_dir:
        save_path = os.path.join(tmp_dir, "saved_config.json")
        save_config(save_data, save_path)

        # verify file was created
        assert os.path.exists(save_path)

        # verify content by reloading
        reloaded_data = load_config(save_path)
        assert reloaded_data == save_data

def test_save_config_creates_directory():
    """test if save_config creates the directory if it doesn't exist."""
    save_data = {"test": "data"}
    with tempfile.TemporaryDirectory() as tmp_base_dir:
        # create a path with a non-existent subdirectory
        non_existent_subdir = os.path.join(tmp_base_dir, "new_subdir")
        save_path = os.path.join(non_existent_subdir, "config.json")

        assert not os.path.exists(non_existent_subdir) # ensure subdir doesn't exist yet
        save_config(save_data, save_path)
        assert os.path.exists(save_path) # check if file was created (implies dir was created)

        # verify content
        reloaded_data = load_config(save_path)
        assert reloaded_data == save_data