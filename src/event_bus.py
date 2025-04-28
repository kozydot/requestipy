import logging
from collections import defaultdict
from typing import Callable, DefaultDict, List, Any

logger = logging.getLogger(__name__)

class EventBus:
    """A simple publish/subscribe event bus."""

    def __init__(self):
        self._subscribers: DefaultDict[str, List[Callable]] = defaultdict(list)
        logger.info("EventBus initialized.")

    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe a callback function to an event type."""
        if not callable(callback):
            logger.error(f"Attempted to subscribe non-callable object to event '{event_type}'")
            return

        self._subscribers[event_type].append(callback)
        logger.debug(f"Callback {callback.__name__} subscribed to event '{event_type}'")

    def unsubscribe(self, event_type: str, callback: Callable):
        """Unsubscribe a callback function from an event type."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
                logger.debug(f"Callback {callback.__name__} unsubscribed from event '{event_type}'")
                # Clean up event type if no subscribers left
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
            except ValueError:
                logger.warning(f"Attempted to unsubscribe callback {callback.__name__} from event '{event_type}', but it was not found.")
        else:
            logger.warning(f"Attempted to unsubscribe from non-existent event type '{event_type}'")

    def publish(self, event_type: str, *args: Any, **kwargs: Any):
        """Publish an event to all subscribed callbacks."""
        if event_type not in self._subscribers:
            logger.debug(f"Published event '{event_type}' but no subscribers found.")
            return

        logger.debug(f"Publishing event '{event_type}' to {len(self._subscribers[event_type])} subscribers.")
        # Iterate over a copy in case a callback modifies the subscriber list during iteration
        for callback in self._subscribers[event_type][:]:
            try:
                # Consider running callbacks in threads/async if they might block
                callback(*args, **kwargs)
                logger.debug(f"Executed callback {callback.__name__} for event '{event_type}'")
            except Exception as e:
                logger.error(f"Error executing callback {callback.__name__} for event '{event_type}': {e}", exc_info=True)

# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    # Set up basic logging for testing this module directly
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    bus = EventBus()

    def handler1(message):
        print(f"Handler 1 received: {message}")

    def handler2(message, sender=None):
        print(f"Handler 2 received: {message} from {sender}")
        # Test unsubscribing from within a handler
        print("Handler 2 unsubscribing Handler 1")
        bus.unsubscribe("test_event", handler1)

    def handler3(message):
        print(f"Handler 3 received: {message}")
        raise ValueError("Handler 3 failed!")


    print("\nSubscribing handlers...")
    bus.subscribe("test_event", handler1)
    bus.subscribe("test_event", handler2)
    bus.subscribe("test_event", handler3)
    bus.subscribe("other_event", handler1)

    print("\nPublishing 'test_event'...")
    bus.publish("test_event", "Hello World!", sender="Main")

    print("\nPublishing 'test_event' again (Handler 1 should be gone)...")
    bus.publish("test_event", "Hello Again!")

    print("\nPublishing 'other_event'...")
    bus.publish("other_event", "Another message")

    print("\nPublishing 'no_subscriber_event'...")
    bus.publish("no_subscriber_event", "This won't be seen")

    print("\nTesting unsubscribe non-existent handler...")
    bus.unsubscribe("test_event", handler1) # Already removed
    bus.unsubscribe("fake_event", handler2) # Non-existent event