import os
import logging
from prometheus_client import start_http_server, Gauge, Counter
import json
from influx_helper import InfluxdbHelper
from subscriber import AMQPSubscriber

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)

# Prometheus metrics
AMQP_CONNECTION_STATUS = Gauge('amqp_connection_status', 'Connection status (1 = up, 0 = down)')
AMQP_MESSAGE_COUNT = Counter('amqp_message_count', 'Number of successfully processed messages')
AMQP_IGNORED_MESSAGE_COUNT = Counter('amqp_ignored_message_count', 'Number of ignored messages')
AMQP_FAILED_MESSAGE_COUNT = Counter('amqp_failed_message_count', 'Number of failed message processing attempts')


# Define a message processing function (this is your functional interface)
def process_message(message):
    logger.info(f"Processing message: {message}")

    try:
        # Extract App.Id and Operation from the message
        app_id = ''
        operation = 'create'
        if isinstance(message, dict):
            logger.debug("Message is a dictionary")
            app_id = message.get('app-id', '')
            operation = message.get('operation', '')
        if isinstance(message, str):
            logger.debug("Message is a string. Converting to dictionary")
            d = json.loads(message)
            app_id = d.get('app-id', '')
            operation = d.get('operation', '')
        if operation=='':
            operation = 'create'

        # If App.Id has a value
        if app_id and app_id.strip():
            logger.info(f"App.Id: {app_id}")
            if operation=='create':
                # Initialize app-specific artefacts in Influxdb, using an InfluxdbHelper instance
                influxdb_helper = InfluxdbHelper(INFLUXDB_URL, ADMIN_TOKEN, ORG_NAME, app_id)
                logger.info(f"Creating App. with Id: {app_id}")
                influxdb_helper.create_all()

                # Store InfluxdbHelper state in an app-state file
                logger.info(f"Storing the state of App. with Id: {app_id}")
                influxdb_helper.saveToFile(f'app-states/state-{app_id}.yaml')
                AMQP_MESSAGE_COUNT.inc()  # Increment success counter
            elif operation=='delete':
                # Find artefact id's and name's for given App.Id
                logger.info(f"Retrieving state of App. with Id: {app_id}")
                influxdb_helper = InfluxdbHelper(INFLUXDB_URL, ADMIN_TOKEN, ORG_NAME, app_id)
                influxdb_helper.find_all(app_id)

                # Delete all artefacts for given App.Id
                logger.info(f"Deleting App. with Id: {app_id}")
                influxdb_helper.delete_all()
                logger.info(f"Deleted App. with Id: {app_id}")
                AMQP_MESSAGE_COUNT.inc()  # Increment success counter
            elif operation=='delete_2':
                # Load the appropriate app-state file
                logger.info(f"Loading state of App. with Id: {app_id}")
                state_file = f'app-states/state-{app_id}.yaml'
                influxdb_helper = InfluxdbHelper('', '', '', '')
                influxdb_helper.loadFromFile(state_file)

                # Delete all artefacts for given App.Id
                logger.info(f"Deleting App. with Id: {app_id}")
                influxdb_helper.delete_all()
                logger.info(f"Deleted App. with Id: {app_id}")
                AMQP_MESSAGE_COUNT.inc()  # Increment success counter
            elif operation=='find_all':
                # Find artefact id's and name's for given App.Id
                logger.info(f"Retrieving state of App. with Id: {app_id}")
                influxdb_helper = InfluxdbHelper(INFLUXDB_URL, ADMIN_TOKEN, ORG_NAME, app_id)
                influxdb_helper.find_all(app_id)
            else:
                logger.warning(f"Unknown operation {operation}. Ignoring the message")
                AMQP_IGNORED_MESSAGE_COUNT.inc()  # Increment ignored counter
            return f"Processed: {message}"
        else:
            logger.warning("App.Id not found. Ignoring the message")
            raise KeyError("App.Id not found")
    except KeyError as e:
        AMQP_IGNORED_MESSAGE_COUNT.inc()  # Increment ignored counter
        raise
    except Exception as e:
        AMQP_FAILED_MESSAGE_COUNT.inc()  # Increment failure counter
        raise

def connection_status(status):
    AMQP_CONNECTION_STATUS.set(status)

if __name__ == "__main__":
    # Retrieve configuration from environment variables
    BROKER_URL = os.getenv("BROKER_URL", "amqp://activemq:5672")
    TOPIC_NAME = os.getenv("TOPIC_NAME", "new_app_topic")

    INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
    ADMIN_TOKEN  = os.getenv("INFLUXDB_ADMIN_TOKEN", "")
    ORG_NAME     = os.getenv("INFLUXDB_ORG_NAME", "my-org")

    # Start Prometheus HTTP server on port 8000 for scraping
    start_http_server(8000)

    # Create subscriber instance and run
    subscriber = AMQPSubscriber(broker_url=BROKER_URL,
                                topic=TOPIC_NAME,
                                message_processor=process_message,
                                connection_status_callback=connection_status)
    subscriber.run()
