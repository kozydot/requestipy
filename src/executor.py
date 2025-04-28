import logging
import threading
from typing import Dict, List, Any

# assuming eventbus and commandmanager are accessible
from src.event_bus import EventBus
from src.command_manager import CommandManager, Command
from src.log_reader import EVENT_COMMAND_DETECTED # import event name

logger = logging.getLogger(__name__)

class Executor:
    """listens for command events and executes them using commandmanager."""

    def __init__(self, config: Dict[str, Any], command_manager: CommandManager, event_bus: EventBus):
        self._config = config # store config
        self._command_manager = command_manager
        self._event_bus = event_bus
        self._subscribe_to_events()
        logger.info("Executor initialized and subscribed to events.")

    def _subscribe_to_events(self):
        """subscribes the command execution handler to the relevant event."""
        self._event_bus.subscribe(EVENT_COMMAND_DETECTED, self.handle_command_event)
        logger.debug(f"executor subscribed to '{EVENT_COMMAND_DETECTED}' event.")

    def handle_command_event(self, user: Dict[str, Any], command: str, args: List[str]):
        """handles the command detected event."""
        # log the raw user dict received
        logger.debug(f"executor received command event: raw user dict={user}, command={command}, args={args}")

        # command name from event includes the prefix '!', remove it for lookup
        command_name = command.lstrip('!')

        cmd_obj: Command | None = self._command_manager.get_command(command_name)

        if cmd_obj:
            # --- admin check ---
            admin_user = self._config.get("admin_user")
            logged_name = user.get("name")
            # add detailed logging for comparison
            logger.debug(f"admin check comparison: logged name='{logged_name}' (type: {type(logged_name)}, len: {len(logged_name) if logged_name else 0}), config name='{admin_user}' (type: {type(admin_user)}, len: {len(admin_user) if admin_user else 0})")
            # strip whitespace from both names before comparing
            is_admin = admin_user and logged_name and logged_name.strip() == admin_user.strip()
            logger.debug(f"admin check result after strip: is_admin={is_admin}") # log result after strip


            if cmd_obj.admin_only and not is_admin:
                logger.warning(f"non-admin user '{user.get('name')}' attempted to run admin command '!{command_name}'. ignoring.")
                # optionally notify user they lack permission
                return # stop processing if not admin for admin-only command

            # --- execute command (if checks pass) ---
            # execute the command (command object handles enabled checks internally)
            try:
                # run in a separate thread to prevent blocking the event handler
                cmd_thread = threading.Thread(target=cmd_obj.execute, args=(user, args), daemon=True)
                cmd_thread.start()
                # cmd_obj.execute(user, args) # synchronous execution (can block)
            except Exception as e:
                logger.error(f"unexpected error trying to start execution thread for command !{cmd_obj.name}: {e}", exc_info=True)
        else:
            logger.warning(f"command '{command_name}' requested by {user['name']} not found.")
            # optionally publish an "unknown_command" event or notify the user

    def shutdown(self):
        """unsubscribes from events."""
        logger.info("executor shutting down...")
        # unsubscribe might be useful if dynamically reloading components
        # self._event_bus.unsubscribe(EVENT_COMMAND_DETECTED, self.handle_command_event)
        # logger.debug(f"executor unsubscribed from '{EVENT_COMMAND_DETECTED}' event.")


# example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # setup mock components
    test_bus = EventBus()
    test_cmd_manager = CommandManager(test_bus)

    def mock_play(user, args):
        print(f"--- mock play --- user: {user['name']}, args: {args}")
        import time
        time.sleep(2) # simulate work
        print(f"--- mock play done ---")

    def mock_help(user, args):
        print(f"--- mock help --- user: {user['name']}, args: {args}")

    test_cmd_manager.register_command("play", mock_play, aliases=["p"])
    test_cmd_manager.register_command("help", mock_help)

    # initialize executor
    executor = Executor(test_cmd_manager, test_bus)

    print("\npublishing command events...")
    dummy_user1 = {"name": "alice", "tags": None}
    dummy_user2 = {"name": "bob", "tags": "*dead*"}

    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user1, command="!play", args=["song", "title"])
    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user2, command="!help", args=[])
    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user1, command="!p", args=["another", "song"]) # test alias
    test_bus.publish(EVENT_COMMAND_DETECTED, user=dummy_user2, command="!unknown", args=["test"]) # test unknown

    print("\nwaiting for commands to finish (due to threading)...")
    # in a real app, the main loop would keep running. here we just wait a bit.
    time.sleep(3)

    print("\nexecutor test finished.")
    # executor.shutdown() # test shutdown if needed