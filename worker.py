import sys
import time
import signal
import logging
from src.config import Config
from src.database.connection import initialize_database
from src.services.agent import agent_instance
from src.workers.application_worker import ApplicationWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("worker")

running = True

def handle_signal(sig, frame):
    global running
    logger.info(f"Received shutdown signal ({sig}). Stopping worker...")
    running = False

def main():
    logger.info("Starting Autonomous Background Job Worker Process...")
    
    # Validate configuration & database
    try:
        Config.validate()
        initialize_database()
        logger.info("Config & Database validated.")
    except Exception as e:
        logger.error(f"Worker startup validation failed: {e}")
        sys.exit(1)

    # Register signal handlers for clean container shutdown
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Start autonomous agent
    logger.info("Starting Autonomous Matching Agent...")
    agent_instance.start()

    # Start application worker
    logger.info("Starting Application Submission Worker...")
    app_worker = ApplicationWorker(interval_seconds=5.0)
    app_worker.start()

    logger.info("Worker process is actively running and waiting for tasks.")

    try:
        while running:
            time.sleep(1.0)
    finally:
        logger.info("Worker shutting down...")
        agent_instance.stop()
        app_worker.stop()
        logger.info("Worker stopped cleanly.")

if __name__ == "__main__":
    main()
