import logging
import threading
from typing import Dict, List, Any

# Assuming EventBus and CommandManager are accessible
from src.event_bus import EventBus
from src.command_manager import CommandManager, Command
from src.log_reader import EVENT_COMMAND_DETECTED # Import event name

logger = logging.getLogger(__name__)

class Executor:
    """Listens for command events and executes them using CommandManager."""

    def __init__(self, config: Dict[str, Any], command_manager: CommandManager, event_bus: EventBus):
        self._config = config # Store config
        self._command_manager = command_manager
        self._event_bus = event_bus
        self._subscribe_to_events()
        logger.info("Executor initialized and subscribed to events.")

    def _subscribe_to_events(self):
        """Subscribes the command execution handler to the relevant event."""
        self._event_bus.subscribe(EVENT_COMMAND_DETECTED, self.handle_command_event)
        logger.debug(f"Executor subscribed to '{EVENT_COMMAND_DETECTED}' event.")

    def handle_command_event(self, user: Dict[str, Any], command: str, args: List[str]):
        """Handles the command detected event."""
        # Log the raw user dict received
        logger.debug(f"Executor received command event: Raw User Dict={user}, Command={command}, Args={args}")

        # Command name from event includes the prefix '!', remove it for lookup
        command_name = command.lstrip('!')

        cmd_obj: Command | None = self._command_manager.get_command(command_name)

        if cmd_obj:
            # --- Admin Check ---
            admin_user = self._config.get("admin_user")
            logged_name = user.get("name")
            # Add detailed logging for comparison
            logger.debug(f"Admin Check Comparison: Logged Name='{logged_name}' (Type: {type(logged_name)}, Len: {len(logged_name) if logged_name else 0}), Config Name='{admin_user}' (Type: {type(admin_user)}, Len: {len(admin_user) if admin_user else 0})")
            # Strip whitespace from both names before comparing
            is_admin = admin_user and logged_name and logged_name.strip() == admin_user.strip()
            logger.debug(f"Admin check result after strip: is_admin={is_admin}") # Log result after strip


            if cmd_obj.admin_only and not is_admin:
                logger.warning(f"Non-admin user '{user.get('name')}' attempted to run admin command '!{command_name}'. Ignoring.")
                # Optionally notify user they lack permission
                return # Stop processing if not admin for admin-only command

            # --- Execute Command (if checks pass) ---
            # Execute the command (Command object handles enabled checks internally)
            try:
                # Run in a separate thread to prevent blocking the event handler
                cmd_thread = threading.Thread(target=cmd_obj.execute, args=(user, args), daemon=True)
                cmd_thread.start()
                # cmd_obj.execute(user, args) # Synchronous execution (can block)
            except Exception as e:
                logger.error(f"Unexpected error trying to start execution thread for command !{cmd_obj.name}: {e}", exc_info=True)
        else:
            logger.warning(f"Command '{command_name}' requested by {user['name']} not found.")
            # Optionally publish an "unknown_command" event or notify the user

    def shutdown(self):
        """Unsubscribes from events."""
        logger.info("Executor shutting down...")
        # Unsubscribe might be useful if dynamically reloading components
        # self._event_bus.unsubscribe(EVENT_COMMAND_DETECTED, self.handle_command_event)
        # logger.debug(f"Executor unsubscribed from '{EVENT_COMMAND_DETECTED}' event.")


# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # Setup mock components
    test_bus = EventBus()
    test_cmd_manager = CommandManager(test_bus)

    def mock_play(user, args):
        print(f"--- MOCK PLAY --- User: {user['name']}, Args: {args}")
        import time
        time.sleep(2) # Simulate work
        print(f"--- MOCK PLAY DONE ---")

    def mock_help(user, args):
        print(f"--- MOCK HELP --- User: {user['name']}, Args: {args}")

    test_cmd_manager.register_command("play", mock_play, aliases=["p"])
    test_cmd_manager.register_command("help", mock_help)

    # Initialize Executor
    executor = Executor(test_cmd_manager, test_bus)

    print("\nPublishing command events...")
    dummy_user1 = {"name": "Alice", "tags": None}
    dummy_user2 = {"name": "Bob", "tags": "*DEAD*"}

    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user1, command="!play", args=["song", "title"])
    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user2, command="!help", args=[])
    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user1, command="!p", args=["another", "song"]) # Test alias
    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user2, command="!unknown", args=["test"]) # Test unknown

    print("\nWaiting for commands to finish (due to threading)...")
    # In a real app, the main loop would keep running. Here we just wait a bit.
    time.sleep(3)

    print("\nExecutor test finished.")
    # executor.shutdown() # Test shutdown if needed