import logging
import queue
import threading
import time
import sounddevice as sd
import soundfile as sf
from typing import Optional, Dict, Any, List # Add List here
from typing import Optional

# Assuming EventBus is accessible if needed for events like playback_started/finished
# from src.event_bus import EventBus

logger = logging.getLogger(__name__)

# Define event names (optional)
EVENT_PLAYBACK_STARTED = "playback_started"
EVENT_PLAYBACK_FINISHED = "playback_finished"
EVENT_PLAYBACK_ERROR = "playback_error"

from typing import Optional, Dict, Any

class AudioPlayer:
    """Handles audio playback using sounddevice and soundfile."""

    def __init__(self, config: Dict[str, Any], event_bus=None): # event_bus is optional for now
        self._config = config
        self._event_bus = event_bus
        self._playback_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._play_queue = queue.Queue() # Queue to hold file paths to play
        self._current_stream: Optional[sd.OutputStream] = None
        self._lock = threading.Lock() # To protect access to shared state like _current_stream
        self._target_device_id: Optional[int] = None # Store the target device ID

        # Find the target device before starting the thread
        self._target_device_id = self._find_output_device_id()

        # Start the consumer thread
        self._start_playback_thread()
        logger.info("AudioPlayer initialized.")

    def _find_output_device_id(self) -> Optional[int]:
        """Finds the output device ID based on the substring in config."""
        device_substring = self._config.get("output_device_substring")
        if not device_substring:
            logger.warning("No 'output_device_substring' found in config. Using default output device.")
            return None # Use default device

        logger.info(f"Searching for output device containing: '{device_substring}'")
        try:
            devices = sd.query_devices()
            logger.debug(f"Available devices: {devices}")
            for i, device in enumerate(devices):
                # Check if it's an output device ('max_output_channels' > 0) and name matches substring
                if device['max_output_channels'] > 0 and device_substring.lower() in device['name'].lower():
                    logger.info(f"Found matching output device: ID={i}, Name='{device['name']}'")
                    return i
            logger.error(f"Could not find an output device matching substring: '{device_substring}'. Using default device.")
            return None # Fallback to default if not found
        except Exception as e:
            logger.error(f"Error querying audio devices: {e}. Using default device.", exc_info=True)
            return None


    def _start_playback_thread(self):
        """Starts the background thread that processes the play queue."""
        if self._playback_thread and self._playback_thread.is_alive():
            logger.warning("Playback thread already running.")
            return
        self._stop_event.clear()
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()
        logger.info("Audio playback thread started.")

    def _playback_loop(self):
        """The main loop for the playback thread."""
        logger.info("Playback loop starting.") # Log thread start
        while True: # Loop indefinitely until shutdown signal (None)
            # --- Ensure stop event is clear at the start of each iteration ---
            self._stop_event.clear()
            logger.debug("Playback loop iteration started, stop event cleared.")

            # --- Check for global shutdown signal (which also sets _stop_event) ---
            # We check the queue for None first, as stop_event might be set for skip/stop
            # file_path = self._play_queue.get(block=True) # Wait indefinitely for an item or None

            try:
                # Wait for a file path in the queue (with timeout to allow checking stop_event)
                file_path = self._play_queue.get(timeout=0.5)
            except queue.Empty:
                # No item in queue, just continue waiting.
                # Do NOT check _stop_event here, as skip/stop shouldn't kill the thread.
                continue # No file to play, loop again

            if file_path is None: # Sentinel value for shutdown
                logger.info("Shutdown sentinel (None) received in queue.")
                break # Exit the main while loop

            # --- Check stop event AGAIN after getting an item, before processing ---
            # This handles the case where stop/skip was called *while* waiting for get()
            if self._stop_event.is_set():
                 logger.info(f"Stop/skip event detected immediately after getting {file_path} from queue. Skipping playback.")
                 self._play_queue.task_done() # Mark item as processed even though skipped
                 # Event will be cleared at the start of the next iteration
                 continue # Go to next loop iteration


            logger.info(f"Attempting to start playback for: {file_path}") # Changed log message slightly
            # --- Load Audio Data ---
            try:
                data, samplerate = sf.read(file_path, dtype='float32')
                logger.debug(f"Loaded audio file: {file_path}, Samplerate: {samplerate}, Shape: {data.shape}")
            except sf.SoundFileError as e:
                logger.error(f"SoundFileError loading {file_path}: {e}")
                if self._event_bus: self._event_bus.publish(EVENT_PLAYBACK_ERROR, file_path=file_path, error=str(e))
                self._play_queue.task_done() # Mark as done even on load failure
                continue # Skip to next item in queue
            except Exception as e:
                logger.error(f"Unexpected error loading audio file {file_path}: {e}", exc_info=True)
                if self._event_bus: self._event_bus.publish(EVENT_PLAYBACK_ERROR, file_path=file_path, error=str(e))
                self._play_queue.task_done()
                continue

            # --- Play Audio using OutputStream and callback ---
            stream = None # Define stream variable outside try
            try:
                # Use soundfile to open the file for reading within the callback
                with sf.SoundFile(file_path, 'r') as audio_file:
                    samplerate = audio_file.samplerate
                    channels = audio_file.channels
                    logger.debug(f"Opened audio file: {file_path}, Samplerate: {samplerate}, Channels: {channels}")

                    # Event to signal callback completion or error
                    stream_finished_event = threading.Event()
                    # Buffer size (number of frames per callback)
                    blocksize = 1024 # Adjust as needed

                    def callback(outdata: memoryview, frames: int, time, status: sd.CallbackFlags):
                        """Callback function to provide audio data to the stream."""
                        if status:
                            logger.warning(f"Playback status flags: {status}")
                            # Signal error if needed, e.g., based on status.output_underflow etc.
                            # stream_finished_event.set() # Signal completion on error?
                            # raise sd.CallbackAbort() # Abort stream on error?

                        # Read requested number of frames from the file
                        read_data = audio_file.read(frames, dtype='float32', always_2d=True)

                        if read_data.shape[0] == 0: # End of file
                            logger.debug("Callback: End of file reached.")
                            outdata[:] = 0 # Fill buffer with silence
                            raise sd.CallbackStop # Signal stream to stop

                        # Copy read data to output buffer
                        outdata[:] = read_data

                        # If less data was read than requested (end of file padding)
                        if read_data.shape[0] < frames:
                            logger.debug(f"Callback: Padding end of stream ({read_data.shape[0]}/{frames} frames).")
                            outdata[read_data.shape[0]:] = 0 # Zero out remaining part of buffer
                            raise sd.CallbackStop # Signal stream to stop after this buffer

                    def finished_callback():
                        """Called when the stream naturally finishes or is stopped/aborted."""
                        logger.debug(f"Stream finished_callback invoked for {file_path}")
                        stream_finished_event.set() # Signal completion/stop

                    logger.debug(f"Attempting to create OutputStream for device ID: {self._target_device_id}")
                    # Create and start the OutputStream, specifying the device
                    stream = sd.OutputStream(
                        device=self._target_device_id, # Use the found device ID (or None for default)
                        samplerate=samplerate,
                        channels=channels,
                        blocksize=blocksize, # Let callback handle buffer size
                        callback=callback,
                        finished_callback=finished_callback
                    )
                    logger.debug(f"OutputStream created. Attempting to start stream...")
                    with self._lock: # Protect stream variable during start/stop
                         self._current_stream = stream # Store ref for stop_playback
                         stream.start() # This call might be blocking/hanging
                         logger.debug(f"OutputStream started successfully for {file_path}")

                    # Wait for the stream to finish (signaled by finished_callback or stop_event)
                    playback_interrupted = False # Flag to track if stopped early
                    while not stream_finished_event.wait(timeout=0.1):
                         if self._stop_event.is_set():
                              logger.info(f"Stop requested during playback of {file_path}. Stopping stream and breaking wait loop.")
                              playback_interrupted = True
                              # --- Try stopping the stream directly here ---
                              try:
                                  # Use the lock to ensure safe access to stream object
                                  with self._lock:
                                      # Check if it's still the current stream and not already stopped
                                      if self._current_stream == stream and stream and not stream.stopped:
                                          logger.debug("Attempting to stop stream directly from wait loop...")
                                          stream.stop() # Stop it now
                                          logger.debug("Stream stopped directly from wait loop.")
                              except Exception as e_stop:
                                  logger.error(f"Error stopping stream directly within wait loop: {e_stop}", exc_info=True)
                              # --- End direct stop attempt ---
                              break # Break the wait loop

                    # --- Cleanup after playback/stop ---
                    # Ensure stream is stopped and closed if it exists
                    with self._lock:
                        if self._current_stream == stream and stream: # Check if it's still the same stream
                            if not stream.stopped: stream.stop()
                            if not stream.closed: stream.close()
                            self._current_stream = None # Clear reference
                            logger.debug(f"Stream stopped and closed for {file_path}")

                    # Log normal finish only if stop wasn't requested AND stream finished naturally
                    if not playback_interrupted and stream_finished_event.is_set():
                        logger.info(f"Finished playback for: {file_path}")
                        if self._event_bus: self._event_bus.publish(EVENT_PLAYBACK_FINISHED, file_path=file_path)
                    elif playback_interrupted:
                        logger.info(f"Playback interrupted for: {file_path}")
                        # DO NOT clear the event here anymore. It's cleared at the start of the loop.
                        # self._stop_event.clear()
                        # logger.debug("Stop event cleared after handling interruption.")


            except sf.SoundFileError as e:
                 logger.error(f"SoundFileError opening/reading {file_path}: {e}")
                 if self._event_bus: self._event_bus.publish(EVENT_PLAYBACK_ERROR, file_path=file_path, error=str(e))
            except sd.PortAudioError as e:
                logger.error(f"PortAudioError during playback for {file_path}: {e}", exc_info=True) # Added exc_info
                if self._event_bus: self._event_bus.publish(EVENT_PLAYBACK_ERROR, file_path=file_path, error=str(e))
            except Exception as e:
                logger.error(f"Unexpected error during playback processing of {file_path}: {e}", exc_info=True) # Changed log message
                if self._event_bus: self._event_bus.publish(EVENT_PLAYBACK_ERROR, file_path=file_path, error=str(e))
            finally:
                # Mark task as done regardless of success/failure
                logger.debug(f"Marking task done for {file_path} in finally block.")
                self._play_queue.task_done()
                # No _current_stream to clear when using sd.play
                # with self._lock:
                #    self._current_stream = None


        logger.warning("Audio playback thread loop exited.") # Changed level to warning


    def play_file(self, file_path: str):
        """Adds a file path to the playback queue."""
        if not isinstance(file_path, str) or not file_path:
             logger.error("Invalid file path provided for playback.")
             return
        # Basic check, ideally validate existence/permissions here or in playback loop
        logger.info(f"Queueing file for playback: {file_path}")
        self._play_queue.put(file_path)

    def stop_playback(self, clear_queue: bool = False): # Default clear_queue to False
        """Signals the playback thread to stop the current track. Optionally clears the queue."""
        logger.info(f"Stop playback requested. Clear queue: {clear_queue}")

        # --- Signal the playback thread ---
        # Set the event. The playback loop's wait() will detect this.
        # The loop itself is responsible for stopping/closing the stream.
        self._stop_event.set()
        logger.debug("Stop event set.")
        # --- End Signal ---

        # Clear the queue if requested (can still do this immediately)
        if clear_queue:
            logger.debug("Clearing playback queue...")
            while not self._play_queue.empty():
                try:
                    self._play_queue.get_nowait()
                    self._play_queue.task_done()
                except queue.Empty:
                    break
                except Exception as e:
                     logger.error(f"Error clearing item from queue: {e}")
            logger.info("Playback queue cleared.")

        # DO NOT clear the stop event here. The playback loop handles it.
        # self._stop_event.clear() # Ensure this line is removed or commented out
        # logger.debug("Stop event cleared, playback loop can continue.") # Ensure this is removed or commented out

    def get_queue_snapshot(self) -> List[str]:
        """Returns a copy of the current items in the playback queue."""
        with self._play_queue.mutex: # Access underlying queue safely
            return list(self._play_queue.queue)


    def shutdown(self):
        """Stops the playback thread and cleans up."""
        logger.info("AudioPlayer shutting down...")
        self.stop_playback(clear_queue=True) # Stop current sound and clear queue
        self._stop_event.set() # Signal the playback loop thread to exit
        self._play_queue.put(None) # Add sentinel value to unblock queue.get()

        if self._playback_thread and self._playback_thread.is_alive():
            logger.debug("Waiting for playback thread to finish...")
            self._playback_thread.join(timeout=2) # Wait for the thread
            if self._playback_thread.is_alive():
                 logger.warning("Playback thread did not shut down gracefully.")
        logger.info("AudioPlayer shut down complete.")


# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # Create a dummy audio file for testing (requires numpy)
    try:
        import numpy as np
        samplerate = 44100
        duration = 3 # seconds
        frequency = 440 # Hz (A4 note)
        t = np.linspace(0., duration, int(samplerate * duration), endpoint=False)
        amplitude = 0.5
        audio_data = amplitude * np.sin(2. * np.pi * frequency * t)
        dummy_file = "dummy_audio.wav"
        sf.write(dummy_file, audio_data, samplerate)
        print(f"Created dummy audio file: {dummy_file}")
    except ImportError:
        print("Numpy not installed, cannot create dummy audio file for testing.")
        dummy_file = None
    except Exception as e:
        print(f"Error creating dummy audio file: {e}")
        dummy_file = None


    player = AudioPlayer()

    if dummy_file:
        print("\nQueueing dummy file...")
        player.play_file(dummy_file)
        player.play_file(dummy_file) # Queue another one

        print("Waiting a bit for playback to start...")
        time.sleep(1)

        print("\nStopping current playback (clearing queue)...")
        player.stop_playback(clear_queue=True)
        time.sleep(0.5) # Give time for stop to process

        print("\nQueueing file again...")
        player.play_file(dummy_file)

        print("Waiting for playback to finish naturally...")
        # Wait until the queue is processed
        player._play_queue.join()
        print("Queue processed.")

    else:
         print("\nSkipping playback test as dummy file could not be created.")


    print("\nShutting down AudioPlayer...")
    player.shutdown()

    # Clean up dummy file
    if dummy_file and os.path.exists(dummy_file):
        try:
            os.remove(dummy_file)
            print(f"Removed dummy audio file: {dummy_file}")
        except OSError as e:
            print(f"Error removing dummy audio file: {e}")

    print("\nAudioPlayer test finished.")