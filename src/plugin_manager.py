import logging
import os
import importlib
import inspect
from typing import List, Dict, Any, Tuple

# assuming commandmanager and eventbus are accessible
from src.command_manager import CommandManager
from src.event_bus import EventBus

logger = logging.getLogger(__name__)

# define convention for plugin registration function
PLUGIN_REGISTER_FUNCTION = "register"
PLUGIN_UNREGISTER_FUNCTION = "unregister" # optional

class PluginInfo:
    """holds information about a loaded plugin."""
    def __init__(self, name: str, module: Any, path: str):
        self.name = name
        self.module = module
        self.path = path
        self.registered = False # track if register function was called successfully
        # optionally store metadata extracted from the plugin module
        self.author = getattr(module, "__author__", "unknown")
        self.version = getattr(module, "__version__", "unknown")
        self.description = getattr(module, "__doc__", "no description").strip() if getattr(module, "__doc__", None) else "no description"

    def __str__(self):
        return f"Plugin(name='{self.name}', version='{self.version}', author='{self.author}', path='{self.path}')"


class PluginManager:
    """loads and manages plugins from a directory."""

    def __init__(self, command_manager: CommandManager, event_bus: EventBus, plugin_dir: str = "plugins"):
        self._command_manager = command_manager
        self._event_bus = event_bus
        # determine plugin directory relative to this file's location or project root
        # assuming project root is parent of src/
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        self._plugin_dir = os.path.join(project_root, plugin_dir)
        self._loaded_plugins: Dict[str, PluginInfo] = {} # name -> plugininfo
        logger.info(f"PluginManager initialized. Plugin directory: {self._plugin_dir}")

    def load_plugins(self):
        """scans the plugin directory, loads valid python modules, and calls their register function."""
        logger.info(f"loading plugins from: {self._plugin_dir}")
        if not os.path.isdir(self._plugin_dir):
            logger.warning(f"plugin directory not found: {self._plugin_dir}. creating it.")
            try:
                os.makedirs(self._plugin_dir)
            except OSError as e:
                logger.error(f"failed to create plugin directory {self._plugin_dir}: {e}")
                return # cannot proceed without plugin directory

        loaded_count = 0
        for filename in os.listdir(self._plugin_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                plugin_name = filename[:-3] # module name without .py
                if plugin_name in self._loaded_plugins:
                    logger.warning(f"plugin '{plugin_name}' already loaded. skipping.")
                    continue

                file_path = os.path.join(self._plugin_dir, filename)
                module_spec = f"{os.path.basename(self._plugin_dir)}.{plugin_name}" # e.g., plugins.myplugin

                try:
                    logger.debug(f"attempting to load plugin module: {module_spec} from {file_path}")
                    # use importlib to load the module
                    module = importlib.import_module(module_spec)
                    # Removed importlib.reload(module) - generally safer for standard loading

                    plugin_info = PluginInfo(name=plugin_name, module=module, path=file_path)
                    logger.info(f"successfully loaded plugin module: {plugin_info.name} (v{plugin_info.version})")

                    # look for the conventional register function
                    if hasattr(module, PLUGIN_REGISTER_FUNCTION) and callable(getattr(module, PLUGIN_REGISTER_FUNCTION)):
                        register_func = getattr(module, PLUGIN_REGISTER_FUNCTION)
                        try:
                            logger.debug(f"calling {PLUGIN_REGISTER_FUNCTION}() for plugin '{plugin_name}'...")
                            # pass necessary managers/context to the plugin
                            register_func(self._command_manager, self._event_bus)
                            plugin_info.registered = True # mark as successfully registered
                            self._loaded_plugins[plugin_name] = plugin_info
                            loaded_count += 1
                            logger.info(f"successfully registered plugin: {plugin_name}")
                        except Exception as e:
                            logger.error(f"error calling {PLUGIN_REGISTER_FUNCTION}() in plugin '{plugin_name}': {e}", exc_info=True)
                    else:
                        logger.warning(f"plugin '{plugin_name}' loaded but has no '{PLUGIN_REGISTER_FUNCTION}(command_manager, event_bus)' function.")
                        # decide if plugins without register function are still "loaded"
                        # self._loaded_plugins[plugin_name] = plugin_info # uncomment to track even if not registered

                except ImportError as e:
                    logger.error(f"failed to import plugin '{plugin_name}' from {file_path}: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"unexpected error loading plugin '{plugin_name}' from {file_path}: {e}", exc_info=True)

        logger.info(f"plugin loading complete. successfully loaded and registered {loaded_count} plugins.")

    def unload_plugins(self):
        """attempts to unload plugins by calling their unregister function (if defined)."""
        logger.info("unloading plugins...")
        unloaded_count = 0
        # iterate over a copy of keys as we might modify the dict
        plugin_names = list(self._loaded_plugins.keys())

        for name in plugin_names:
            plugin_info = self._loaded_plugins.get(name)
            if not plugin_info: continue # should not happen if iterating keys

            logger.debug(f"attempting to unload plugin: {name}")
            # call unregister function if it exists
            if hasattr(plugin_info.module, PLUGIN_UNREGISTER_FUNCTION) and callable(getattr(plugin_info.module, PLUGIN_UNREGISTER_FUNCTION)):
                unregister_func = getattr(plugin_info.module, PLUGIN_UNREGISTER_FUNCTION)
                try:
                    logger.debug(f"calling {PLUGIN_UNREGISTER_FUNCTION}() for plugin '{name}'...")
                    # pass context if needed by unregister function
                    unregister_func(self._command_manager, self._event_bus)
                    logger.info(f"successfully called unregister for plugin: {name}")
                except Exception as e:
                    logger.error(f"error calling {PLUGIN_UNREGISTER_FUNCTION}() in plugin '{name}': {e}", exc_info=True)
            else:
                 logger.debug(f"plugin '{name}' has no '{PLUGIN_UNREGISTER_FUNCTION}' function.")

            # remove from loaded plugins list
            del self._loaded_plugins[name]
            unloaded_count += 1
            # note: python doesn't truly unload modules easily. this primarily
            # calls the cleanup function and removes it from our manager.
            # for true unloading, more complex mechanisms or process restarts are needed.

        logger.info(f"plugin unloading complete. unloaded {unloaded_count} plugins.")


    def get_loaded_plugins(self) -> List[PluginInfo]:
        """returns a list of loaded plugin information."""
        return list(self._loaded_plugins.values())


# example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # create dummy components and plugin directory for testing
    TEST_PLUGIN_DIR = "temp_test_plugins"
    if not os.path.exists(TEST_PLUGIN_DIR): os.makedirs(TEST_PLUGIN_DIR)

    # create dummy plugin files
    plugin1_content = """
__author__ = "tester"
__version__ = "1.0"
\"\"\"a dummy test plugin.\"\"\"
import logging

logger = logging.getlogger(__name__)

def register(command_manager, event_bus):
    logger.info("plugin 1 registering...")
    command_manager.register_command("plugincmd", cmd_plugin, help_text="command from plugin 1", source="plugin1")
    event_bus.subscribe("some_event", handle_some_event)
    logger.info("plugin 1 registered.")

def unregister(command_manager, event_bus):
     logger.info("plugin 1 unregistering...")
     command_manager.unregister_command("plugincmd")
     event_bus.unsubscribe("some_event", handle_some_event)
     logger.info("plugin 1 unregistered.")

def cmd_plugin(user, args):
    print(f"--- plugin 1 cmd --- user: {user['name']}, args: {args}")

def handle_some_event(*args, **kwargs):
     print(f"--- plugin 1 event handler --- args: {args}, kwargs: {kwargs}")
"""
    plugin2_content = """
# no register function
import logging
logger = logging.getlogger(__name__)
logger.info("plugin 2 loaded (no register function).")
"""
    plugin3_content = """
import logging
logger = logging.getlogger(__name__)

def register(command_manager, event_bus):
     logger.info("plugin 3 registering...")
     # this will cause an error during registration
     raise valueerror("plugin 3 failed to register!")
"""

    with open(os.path.join(TEST_PLUGIN_DIR, "plugin1.py"), "w") as f: f.write(plugin1_content)
    with open(os.path.join(TEST_PLUGIN_DIR, "plugin2.py"), "w") as f: f.write(plugin2_content)
    with open(os.path.join(TEST_PLUGIN_DIR, "plugin3_error.py"), "w") as f: f.write(plugin3_content)
    # add __init__.py to make it a package
    with open(os.path.join(TEST_PLUGIN_DIR, "__init__.py"), "w") as f: f.write("")


    # mock managers
    mock_bus = EventBus()
    mock_cmd_manager = CommandManager(mock_bus)

    # initialize pluginmanager using the test directory
    # need to adjust path finding if running directly vs imported
    # for direct run, assume test_plugin_dir is relative to cwd
    plugin_manager = PluginManager(mock_cmd_manager, mock_bus, plugin_dir=TEST_PLUGIN_DIR)

    print("\n--- loading plugins ---")
    plugin_manager.load_plugins()

    print("\n--- loaded plugins ---")
    for p_info in plugin_manager.get_loaded_plugins():
        print(f"- {p_info}")

    print("\n--- testing plugin command ---")
    cmd = mock_cmd_manager.get_command("plugincmd")
    if cmd:
        cmd.execute({"name": "testuser"}, ["arg1"])
    else:
        print("plugin command 'plugincmd' not found.")

    print("\n--- testing plugin event ---")
    mock_bus.publish("some_event", data="test data")

    print("\n--- unloading plugins ---")
    plugin_manager.unload_plugins()

    print("\n--- loaded plugins after unload ---")
    for p_info in plugin_manager.get_loaded_plugins():
        print(f"- {p_info}") # should be empty

    print("\n--- testing plugin command after unload ---")
    cmd_after = mock_cmd_manager.get_command("plugincmd")
    if cmd_after:
         print("error: command 'plugincmd' still exists after unload.")
         cmd_after.execute({"name": "testuser"}, ["arg1"])
    else:
        print("plugin command 'plugincmd' successfully removed.")


    # clean up dummy directory
    import shutil
    if os.path.exists(TEST_PLUGIN_DIR): shutil.rmtree(TEST_PLUGIN_DIR)
    print(f"\nremoved test plugin directory: {TEST_PLUGIN_DIR}")

    print("\npluginmanager test finished.")