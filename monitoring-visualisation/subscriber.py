import logging
import random
import threading
import time
import queue
from proton import Message
from proton._reactor import Backoff
from proton.handlers import MessagingHandler
from proton.reactor import Container

# Configure logging
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)

class AMQPSubscriber(MessagingHandler):
    def __init__(self,
                 broker_url,
                 topic,
                 message_processor,
                 max_retries=10,
                 initial_reconnect_interval=5,
                 max_reconnect_interval=60,
                 connection_status_callback=None
                 ):
        super().__init__()
        self.broker_url = broker_url
        self.topic = f'topic://{topic}' if '://' not in topic else topic
        self.connection = None
        self.receiver = None
        self.container = None
        self.message_processor = message_processor  # Store the message processor (function)

        # Reconnection settings
        self.max_retries = max_retries
        self.retry_count = 0
        self.initial_reconnect_interval = initial_reconnect_interval
        self.max_reconnect_interval = max_reconnect_interval
        self.current_reconnect_interval = initial_reconnect_interval

        # Callbacks
        self.connection_status_callback = connection_status_callback

        # Flags
        self.should_reconnect = True

        # Message queue for async processing
        self.message_queue = queue.Queue()

        # Start message processing thread
        self.processing_thread = threading.Thread(target=self._process_messages, daemon=True)
        self.processing_thread.start()

    def on_start(self, event):
        """Start the connection and subscribe to the topic."""
        self.container = event.container  # Save container reference
        self._connect()

    def _connect(self):
        """Connect to the broker and subscribe to the topic."""
        if not self.should_reconnect:
            return  # Prevent reconnecting if disconnect() was called

        try:
            logger.info(f"Connecting to {self.broker_url} and subscribing to {self.topic}...")
            reconnect_strategy = Backoff(initial=self.initial_reconnect_interval, max_delay=self.max_reconnect_interval, factor=1.5)  # Custom reconnect config
            self.connection = self.container.connect(self.broker_url, heartbeat=10, reconnect=reconnect_strategy)
            self.receiver = self.container.create_receiver(self.connection, self.topic)
            self.retry_count = 0  # Reset retry count on success
            self.current_reconnect_interval = self.initial_reconnect_interval  # Reset backoff
            self.connection_status_callback(1)  # Set connection status to 'up'
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.connection_status_callback(1)  # Set connection status to 'down'
            # self._schedule_reconnect()

    # def on_connection_opened(self, event):
    #     logger.info(f"Connected to {self.broker_url}")

    def on_message(self, event):
        """Handle incoming messages asynchronously."""
        try:
            self.message_queue.put(event.message.body)
        except Exception as e:
            logger.error(f"Error queuing message: {e}")

    def _process_messages(self):
        """Continuously process messages from the queue."""
        while True:
            msg = self.message_queue.get()
            if msg is None:  # Exit signal
                break
            try:
                # Call the passed message processor function
                processed_message = self.message_processor(msg)
                logger.info(f"Processed message: {processed_message}")
                # Simulate message processing failure
                if "error" in msg:
                    raise ValueError("Simulated processing failure")
            except Exception as e:
                logger.error(f"Message processing failed: {e}\nmessage: {msg}\n", exc_info=True)
                self._send_to_dead_letter_queue(msg, str(e))

    def _send_to_dead_letter_queue(self, message_body, reason):
        """Send failed messages to a Dead Letter Queue (DLQ)."""
        try:
            dlq_name = f"{self.topic}.DLQ"
            sender = self.container.create_sender(self.connection, dlq_name)
            sender.send(Message(body={
                "message": message_body,
                "reason": reason
            }))
            logger.warning(f"Message moved to Dead Letter Queue: {dlq_name}")
        except Exception as e:
            logger.error(f"Failed to send message to DLQ: {e}")

    def on_transport_error(self, event):
        """Handle connection errors and attempt to reconnect with backoff."""
        logger.error(f"Connection lost! Error: {event.transport.condition}")
        self.connection_status_callback(0)  # Set connection status to 'down'
        # self._schedule_reconnect()

    # """Method 'on_disconnected' is disabled since Proton has its own reconnect facility."""
    # def on_disconnected(self, event):
    #     """Handle unexpected disconnection and attempt to reconnect with backoff."""
    #     if self.should_reconnect:
    #         logger.warning("Disconnected from broker! Attempting to reconnect...")
    #         self._schedule_reconnect()
    #     else:
    #         logger.info("Disconnected from broker (user-requested).")

    # """Method '_schedule_reconnect' is disabled since Proton has its own reconnect facility."""
    # def _schedule_reconnect(self):
    #     """Schedule a reconnection attempt using exponential backoff with jitter."""
    #     if not self.should_reconnect or self.retry_count >= self.max_retries:
    #         logger.error("Max retries reached. Stopping subscriber.")
    #         return
    #
    #     try:
    #         jitter = random.uniform(0, self.current_reconnect_interval * 0.2)  # Add some randomness
    #         delay = min(self.current_reconnect_interval + jitter, self.max_reconnect_interval)
    #
    #         logger.info(f"Reconnecting in {delay:.2f} seconds (Attempt {self.retry_count + 1}/{self.max_retries})...")
    #         #AMQP_RECONNECT_ATTEMPTS.inc()  # Increment reconnect attempts counter
    #         threading.Timer(delay, self._reconnect).start()
    #
    #         self.retry_count += 1
    #         self.current_reconnect_interval = min(self.current_reconnect_interval * 2, self.max_reconnect_interval)
    #     except Exception as e:
    #         logger.error(f"Error scheduling reconnect: {e}")

    # def _reconnect(self):
    #     """Attempt to reconnect."""
    #     if not self.should_reconnect:
    #         return  # Prevent reconnecting if disconnect() was called
    #
    #     try:
    #         self._connect()
    #     except Exception as e:
    #         logger.error(f"Reconnect failed: {e}")
    #         self._schedule_reconnect()

    def disconnect(self):
        """Gracefully disconnect from the broker and stop reconnection attempts."""
        try:
            self.should_reconnect = False  # Prevent further reconnection attempts
            if self.connection:
                logger.info("Closing connection...")
                self.connection.close()
                self.connection = None
            if self.container:
                logger.info("Shutting down the subscriber...")
                self.container.stop()  # Stop the Proton event loop
            self.message_queue.put(None)  # Signal the processing thread to exit
            self.processing_thread.join()
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")

    def run(self):
        container = Container(self)

        # Run the subscriber in the Proton event loop (this will run indefinitely until a signal is received)
        logger.info("AMQP Subscriber is running... Press Ctrl+C to exit.")
        while True:
            try:
                container.run()  # This will run forever until a signal is received
            except KeyboardInterrupt:
                logger.info("Graceful shutdown triggered by user (Ctrl+C).")
                self.disconnect()  # Disconnect cleanly
                break  # Exit the loop after disconnecting
            except Exception as e:
                logger.error(f"Unexpected error occurred: {e}")
                logger.info("Restarting the subscriber after error...")
                time.sleep(5)  # Wait before restarting the subscriber to avoid tight looping
                # Reconnect and continue running
                self.disconnect()  # Ensure the previous connection is closed
                container = Container(self)  # Reinitialize container
                self._connect()  # Attempt to reconnect
