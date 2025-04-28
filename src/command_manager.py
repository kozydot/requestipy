import logging
from typing import Callable, Dict, List, Optional, Any

# Assuming EventBus is accessible
from src.event_bus import EventBus

logger = logging.getLogger(__name__)

# Type alias for command functions
# Command function signature: func(user: Dict, args: List[str], **kwargs) -> None
# user dict example: {"name": "PlayerName", "tags": "*DEAD*"}
CommandCallable = Callable[[Dict[str, Any], List[str]], None]

class Command:
    """Represents a registered command."""
    def __init__(self, name: str, func: CommandCallable, help_text: str = "", aliases: Optional[List[str]] = None, admin_only: bool = False, source: str = "core"):
        self.name = name.lower() # Store command names in lowercase
        self.func = func
        self.help_text = help_text
        self.aliases = [alias.lower() for alias in aliases] if aliases else []
        self.admin_only = admin_only
        self.source = source # e.g., 'core' or plugin name
        self.enabled = True # Commands are enabled by default

    def execute(self, user: Dict[str, Any], args: List[str]):
        """Executes the command's function."""
        if not self.enabled:
            logger.warning(f"Attempted to execute disabled command: !{self.name}")
            # Optionally notify user or event bus
            return

        # TODO: Add admin check logic here if needed, potentially using config
        # if self.admin_only and not is_admin(user):
        #     logger.warning(f"User {user['name']} attempted to run admin command !{self.name}")
        #     # Notify user?
        #     return

        try:
            logger.info(f"Executing command !{self.name} for user {user['name']} with args: {args}")
            self.func(user, args)
        except Exception as e:
            logger.error(f"Error executing command !{self.name}: {e}", exc_info=True)
            # Optionally notify user or event bus about the error

    def __str__(self):
        return f"Command(name='{self.name}', aliases={self.aliases}, source='{self.source}', enabled={self.enabled})"


class CommandManager:
    """Manages registration and lookup of commands."""

    def __init__(self, event_bus: EventBus):
        self._commands: Dict[str, Command] = {} # Maps name/alias to Command object
        self._event_bus = event_bus # May be used for events like command_registered
        logger.info("CommandManager initialized.")

    def register_command(self, name: str, func: CommandCallable, help_text: str = "", aliases: Optional[List[str]] = None, admin_only: bool = False, source: str = "core") -> bool:
        """Registers a new command."""
        command_name = name.lower()
        if command_name in self._commands:
            logger.error(f"Command registration failed: Name '{command_name}' already registered by {self._commands[command_name].source}.")
            return False

        # Check aliases for conflicts
        if aliases:
            for alias in aliases:
                alias_lower = alias.lower()
                if alias_lower in self._commands:
                     logger.error(f"Command registration failed: Alias '{alias_lower}' for command '{command_name}' already registered by {self._commands[alias_lower].source}.")
                     return False

        # Create and store command
        command = Command(name=command_name, func=func, help_text=help_text, aliases=aliases, admin_only=admin_only, source=source)
        self._commands[command_name] = command
        if aliases:
            for alias in command.aliases:
                self._commands[alias] = command # Map aliases directly to the command object

        logger.info(f"Command registered: !{command_name} (Aliases: {command.aliases}, Source: {source})")
        # Optionally publish an event
        # self._event_bus.publish("command_registered", command=command)
        return True

    def unregister_command(self, name: str) -> bool:
        """Unregisters a command and its aliases."""
        command_name = name.lower()
        command = self._commands.get(command_name)

        if not command or command.name != command_name: # Ensure we are removing the main name, not an alias
             logger.warning(f"Command unregistration failed: Command '{command_name}' not found or '{name}' is an alias.")
             return False

        # Remove main name
        del self._commands[command_name]

        # Remove aliases
        if command.aliases:
            for alias in command.aliases:
                if alias in self._commands and self._commands[alias] == command:
                    del self._commands[alias]

        logger.info(f"Command unregistered: !{command_name} (Source: {command.source})")
        # Optionally publish an event
        # self._event_bus.publish("command_unregistered", command_name=command_name, source=command.source)
        return True

    def get_command(self, name: str) -> Optional[Command]:
        """Finds a command by its name or alias."""
        logger.debug(f"Looking up command/alias for raw input: '{name}'") # Log raw input
        name_lower = name.lower() # Convert to lowercase
        logger.debug(f"Attempting lookup with lowercased name: '{name_lower}'")
        command = self._commands.get(name_lower)
        logger.debug(f"Lookup result: {'Found' if command else 'Not Found'}") # Log result
        return command

    def get_all_commands(self) -> List[Command]:
        """Returns a list of unique registered command objects."""
        # Use a set to get unique command objects, as aliases point to the same object
        return list({cmd for cmd in self._commands.values()})

    def enable_command(self, name: str):
        """Enables a command."""
        command = self.get_command(name)
        if command:
            command.enabled = True
            logger.info(f"Command !{command.name} enabled.")
        else:
            logger.warning(f"Could not enable command: !{name} not found.")

    def disable_command(self, name: str):
        """Disables a command."""
        command = self.get_command(name)
        if command:
            command.enabled = False
            logger.info(f"Command !{command.name} disabled.")
        else:
            logger.warning(f"Could not disable command: !{name} not found.")


# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    test_bus = EventBus() # Dummy event bus for testing
    manager = CommandManager(test_bus)

    def cmd_hello(user, args):
        print(f"Hello {user['name']}! Args: {args}")

    def cmd_test(user, args):
        print(f"Test command executed by {user['name']}. Args: {args}")

    print("\nRegistering commands...")
    manager.register_command("hello", cmd_hello, help_text="Says hello.", aliases=["hi", "hey"])
    manager.register_command("test", cmd_test, help_text="A test command.", source="plugin_A")
    manager.register_command("HI", cmd_hello) # Test duplicate alias registration (should fail)
    manager.register_command("fail", cmd_hello, aliases=["test"]) # Test duplicate alias (should fail)

    print("\nGetting commands...")
    cmd_obj_hello = manager.get_command("hello")
    cmd_obj_hi = manager.get_command("hi")
    cmd_obj_test = manager.get_command("test")
    cmd_obj_none = manager.get_command("nonexistent")

    print(f"Found 'hello': {cmd_obj_hello}")
    print(f"Found 'hi': {cmd_obj_hi}")
    print(f"Found 'test': {cmd_obj_test}")
    print(f"Found 'nonexistent': {cmd_obj_none}")
    print(f"Are 'hello' and 'hi' the same object? {cmd_obj_hello is cmd_obj_hi}")

    print("\nExecuting commands...")
    dummy_user = {"name": "Tester", "tags": None}
    if cmd_obj_hello: cmd_obj_hello.execute(dummy_user, ["arg1", "arg2"])
    if cmd_obj_hi: cmd_obj_hi.execute(dummy_user, []) # Execute via alias
    if cmd_obj_test: cmd_obj_test.execute(dummy_user, ["test_arg"])

    print("\nDisabling 'hello'...")
    manager.disable_command("hello")
    print(f"'hello' enabled: {cmd_obj_hello.enabled if cmd_obj_hello else 'N/A'}")
    print("Executing 'hello' (should not run)...")
    if cmd_obj_hello: cmd_obj_hello.execute(dummy_user, ["arg3"])
    print("Executing 'hi' (should not run)...")
    if cmd_obj_hi: cmd_obj_hi.execute(dummy_user, [])

    print("\nEnabling 'hello'...")
    manager.enable_command("hello")
    print(f"'hello' enabled: {cmd_obj_hello.enabled if cmd_obj_hello else 'N/A'}")
    print("Executing 'hi' (should run now)...")
    if cmd_obj_hi: cmd_obj_hi.execute(dummy_user, [])

    print("\nUnregistering 'hello'...")
    manager.unregister_command("hello")
    cmd_obj_hello_after = manager.get_command("hello")
    cmd_obj_hi_after = manager.get_command("hi")
    print(f"Found 'hello' after unregister: {cmd_obj_hello_after}")
    print(f"Found 'hi' after unregister: {cmd_obj_hi_after}") # Alias should also be gone

    print("\nAll Commands:")
    for cmd in manager.get_all_commands():
        print(f"- {cmd}")