import logging
import os
import importlib
import inspect
from typing import List, Dict, Any, Tuple

# Assuming CommandManager and EventBus are accessible
from src.command_manager import CommandManager
from src.event_bus import EventBus

logger = logging.getLogger(__name__)

# Define convention for plugin registration function
PLUGIN_REGISTER_FUNCTION = "register"
PLUGIN_UNREGISTER_FUNCTION = "unregister" # Optional

class PluginInfo:
    """Holds information about a loaded plugin."""
    def __init__(self, name: str, module: Any, path: str):
        self.name = name
        self.module = module
        self.path = path
        self.registered = False # Track if register function was called successfully
        # Optionally store metadata extracted from the plugin module
        self.author = getattr(module, "__author__", "Unknown")
        self.version = getattr(module, "__version__", "Unknown")
        self.description = getattr(module, "__doc__", "No description").strip() if getattr(module, "__doc__", None) else "No description"

    def __str__(self):
        return f"Plugin(name='{self.name}', version='{self.version}', author='{self.author}', path='{self.path}')"


class PluginManager:
    """Loads and manages plugins from a directory."""

    def __init__(self, command_manager: CommandManager, event_bus: EventBus, plugin_dir: str = "plugins"):
        self._command_manager = command_manager
        self._event_bus = event_bus
        # Determine plugin directory relative to this file's location or project root
        # Assuming project root is parent of src/
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self._plugin_dir = os.path.join(project_root, plugin_dir)
        self._loaded_plugins: Dict[str, PluginInfo] = {} # name -> PluginInfo
        logger.info(f"PluginManager initialized. Plugin directory: {self._plugin_dir}")

    def load_plugins(self):
        """Scans the plugin directory, loads valid Python modules, and calls their register function."""
        logger.info(f"Loading plugins from: {self._plugin_dir}")
        if not os.path.isdir(self._plugin_dir):
            logger.warning(f"Plugin directory not found: {self._plugin_dir}. Creating it.")
            try:
                os.makedirs(self._plugin_dir)
            except OSError as e:
                logger.error(f"Failed to create plugin directory {self._plugin_dir}: {e}")
                return # Cannot proceed without plugin directory

        loaded_count = 0
        for filename in os.listdir(self._plugin_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                plugin_name = filename[:-3] # Module name without .py
                if plugin_name in self._loaded_plugins:
                    logger.warning(f"Plugin '{plugin_name}' already loaded. Skipping.")
                    continue

                file_path = os.path.join(self._plugin_dir, filename)
                module_spec = f"{os.path.basename(self._plugin_dir)}.{plugin_name}" # e.g., plugins.myplugin

                try:
                    logger.debug(f"Attempting to load plugin module: {module_spec} from {file_path}")
                    # Use importlib to load the module
                    module = importlib.import_module(module_spec)
                    importlib.reload(module) # Useful for development/reloading

                    plugin_info = PluginInfo(name=plugin_name, module=module, path=file_path)
                    logger.info(f"Successfully loaded plugin module: {plugin_info.name} (v{plugin_info.version})")

                    # Look for the conventional register function
                    if hasattr(module, PLUGIN_REGISTER_FUNCTION) and callable(getattr(module, PLUGIN_REGISTER_FUNCTION)):
                        register_func = getattr(module, PLUGIN_REGISTER_FUNCTION)
                        try:
                            logger.debug(f"Calling {PLUGIN_REGISTER_FUNCTION}() for plugin '{plugin_name}'...")
                            # Pass necessary managers/context to the plugin
                            register_func(self._command_manager, self._event_bus)
                            plugin_info.registered = True # Mark as successfully registered
                            self._loaded_plugins[plugin_name] = plugin_info
                            loaded_count += 1
                            logger.info(f"Successfully registered plugin: {plugin_name}")
                        except Exception as e:
                            logger.error(f"Error calling {PLUGIN_REGISTER_FUNCTION}() in plugin '{plugin_name}': {e}", exc_info=True)
                    else:
                        logger.warning(f"Plugin '{plugin_name}' loaded but has no '{PLUGIN_REGISTER_FUNCTION}(command_manager, event_bus)' function.")
                        # Decide if plugins without register function are still "loaded"
                        # self._loaded_plugins[plugin_name] = plugin_info # Uncomment to track even if not registered

                except ImportError as e:
                    logger.error(f"Failed to import plugin '{plugin_name}' from {file_path}: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"Unexpected error loading plugin '{plugin_name}' from {file_path}: {e}", exc_info=True)

        logger.info(f"Plugin loading complete. Successfully loaded and registered {loaded_count} plugins.")

    def unload_plugins(self):
        """Attempts to unload plugins by calling their unregister function (if defined)."""
        logger.info("Unloading plugins...")
        unloaded_count = 0
        # Iterate over a copy of keys as we might modify the dict
        plugin_names = list(self._loaded_plugins.keys())

        for name in plugin_names:
            plugin_info = self._loaded_plugins.get(name)
            if not plugin_info: continue # Should not happen if iterating keys

            logger.debug(f"Attempting to unload plugin: {name}")
            # Call unregister function if it exists
            if hasattr(plugin_info.module, PLUGIN_UNREGISTER_FUNCTION) and callable(getattr(plugin_info.module, PLUGIN_UNREGISTER_FUNCTION)):
                unregister_func = getattr(plugin_info.module, PLUGIN_UNREGISTER_FUNCTION)
                try:
                    logger.debug(f"Calling {PLUGIN_UNREGISTER_FUNCTION}() for plugin '{name}'...")
                    # Pass context if needed by unregister function
                    unregister_func(self._command_manager, self._event_bus)
                    logger.info(f"Successfully called unregister for plugin: {name}")
                except Exception as e:
                    logger.error(f"Error calling {PLUGIN_UNREGISTER_FUNCTION}() in plugin '{name}': {e}", exc_info=True)
            else:
                 logger.debug(f"Plugin '{name}' has no '{PLUGIN_UNREGISTER_FUNCTION}' function.")

            # Remove from loaded plugins list
            del self._loaded_plugins[name]
            unloaded_count += 1
            # Note: Python doesn't truly unload modules easily. This primarily
            # calls the cleanup function and removes it from our manager.
            # For true unloading, more complex mechanisms or process restarts are needed.

        logger.info(f"Plugin unloading complete. Unloaded {unloaded_count} plugins.")


    def get_loaded_plugins(self) -> List[PluginInfo]:
        """Returns a list of loaded plugin information."""
        return list(self._loaded_plugins.values())


# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # Create dummy components and plugin directory for testing
    TEST_PLUGIN_DIR = "temp_test_plugins"
    if not os.path.exists(TEST_PLUGIN_DIR): os.makedirs(TEST_PLUGIN_DIR)

    # Create dummy plugin files
    plugin1_content = """
__author__ = "Tester"
__version__ = "1.0"
\"\"\"A dummy test plugin.\"\"\"
import logging

logger = logging.getLogger(__name__)

def register(command_manager, event_bus):
    logger.info("Plugin 1 registering...")
    command_manager.register_command("plugincmd", cmd_plugin, help_text="Command from plugin 1", source="plugin1")
    event_bus.subscribe("some_event", handle_some_event)
    logger.info("Plugin 1 registered.")

def unregister(command_manager, event_bus):
     logger.info("Plugin 1 unregistering...")
     command_manager.unregister_command("plugincmd")
     event_bus.unsubscribe("some_event", handle_some_event)
     logger.info("Plugin 1 unregistered.")

def cmd_plugin(user, args):
    print(f"--- PLUGIN 1 CMD --- User: {user['name']}, Args: {args}")

def handle_some_event(*args, **kwargs):
     print(f"--- PLUGIN 1 EVENT HANDLER --- Args: {args}, Kwargs: {kwargs}")
"""
    plugin2_content = """
# No register function
import logging
logger = logging.getLogger(__name__)
logger.info("Plugin 2 loaded (no register function).")
"""
    plugin3_content = """
import logging
logger = logging.getLogger(__name__)

def register(command_manager, event_bus):
     logger.info("Plugin 3 registering...")
     # This will cause an error during registration
     raise ValueError("Plugin 3 failed to register!")
"""

    with open(os.path.join(TEST_PLUGIN_DIR, "plugin1.py"), "w") as f: f.write(plugin1_content)
    with open(os.path.join(TEST_PLUGIN_DIR, "plugin2.py"), "w") as f: f.write(plugin2_content)
    with open(os.path.join(TEST_PLUGIN_DIR, "plugin3_error.py"), "w") as f: f.write(plugin3_content)
    # Add __init__.py to make it a package
    with open(os.path.join(TEST_PLUGIN_DIR, "__init__.py"), "w") as f: f.write("")


    # Mock managers
    mock_bus = EventBus()
    mock_cmd_manager = CommandManager(mock_bus)

    # Initialize PluginManager using the test directory
    # Need to adjust path finding if running directly vs imported
    # For direct run, assume TEST_PLUGIN_DIR is relative to cwd
    plugin_manager = PluginManager(mock_cmd_manager, mock_bus, plugin_dir=TEST_PLUGIN_DIR)

    print("\n--- Loading Plugins ---")
    plugin_manager.load_plugins()

    print("\n--- Loaded Plugins ---")
    for p_info in plugin_manager.get_loaded_plugins():
        print(f"- {p_info}")

    print("\n--- Testing Plugin Command ---")
    cmd = mock_cmd_manager.get_command("plugincmd")
    if cmd:
        cmd.execute({"name": "TestUser"}, ["arg1"])
    else:
        print("Plugin command 'plugincmd' not found.")

    print("\n--- Testing Plugin Event ---")
    mock_bus.publish("some_event", data="test data")

    print("\n--- Unloading Plugins ---")
    plugin_manager.unload_plugins()

    print("\n--- Loaded Plugins After Unload ---")
    for p_info in plugin_manager.get_loaded_plugins():
        print(f"- {p_info}") # Should be empty

    print("\n--- Testing Plugin Command After Unload ---")
    cmd_after = mock_cmd_manager.get_command("plugincmd")
    if cmd_after:
         print("ERROR: Command 'plugincmd' still exists after unload.")
         cmd_after.execute({"name": "TestUser"}, ["arg1"])
    else:
        print("Plugin command 'plugincmd' successfully removed.")


    # Clean up dummy directory
    import shutil
    if os.path.exists(TEST_PLUGIN_DIR): shutil.rmtree(TEST_PLUGIN_DIR)
    print(f"\nRemoved test plugin directory: {TEST_PLUGIN_DIR}")

    print("\nPluginManager test finished.")