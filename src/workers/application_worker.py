import logging
import threading
import time
import random
from src.services.application_queue import get_next_queued_application, update_status

logger = logging.getLogger(__name__)

class ApplicationWorker(threading.Thread):
    def __init__(self, interval_seconds: float = 2.0, simulate_failure_rate: float = 0.0):
        """
        Background worker that continuously fetches and processes jobs from the application queue.
        """
        super().__init__()
        self.daemon = True
        self.interval_seconds = interval_seconds
        self.simulate_failure_rate = simulate_failure_rate
        self.running = True

    def run(self):
        logger.info("[Application Worker] Starting worker thread loop...")
        while self.running:
            try:
                task = get_next_queued_application()
                if task:
                    self.process_task(task)
                else:
                    time.sleep(self.interval_seconds)
            except Exception as e:
                logger.error(f"[Application Worker] Error in worker loop: {e}")
                time.sleep(self.interval_seconds)
        logger.info("[Application Worker] Worker thread loop stopped.")

    def process_task(self, task: dict):
        from src.services.agent import agent_instance

        queue_id = task["id"]
        resume_id = task["resume_id"]
        job_id = task["job_id"]
        attempts = task["attempts"] + 1

        msg_start = f"[Application Worker] Starting job application for job {job_id[:8]} (Attempt {attempts}/3)..."
        logger.info(msg_start)
        agent_instance.log_and_broadcast(msg_start, "status")
        
        try:
            # Placeholder for future application workflow (browser automation/APIs by agent)
            time.sleep(2.0)  # Simulate processing delay & form filling by agent
            
            if random.random() < self.simulate_failure_rate:
                raise RuntimeError("Simulated network submission timeout error.")

            msg_success = f"[Application Worker] Application {queue_id[:8]} for job {job_id[:8]} successfully submitted!"
            logger.info(msg_success)
            agent_instance.log_and_broadcast(msg_success, "success")
            update_status(queue_id, "COMPLETED", attempts=attempts)
        except Exception as err:
            logger.warning(f"[Application Worker] Application submission failed: {err}")
            if attempts >= 3:
                msg_fail = f"[Application Worker] Application {queue_id[:8]} reached max retries. Status: FAILED."
                logger.error(msg_fail)
                agent_instance.log_and_broadcast(msg_fail, "error")
                update_status(queue_id, "FAILED", error_msg=str(err), attempts=attempts)
            else:
                msg_retry = f"[Application Worker] Scheduling application {queue_id[:8]} for RETRY."
                logger.info(msg_retry)
                agent_instance.log_and_broadcast(msg_retry, "warning")
                update_status(queue_id, "RETRY", error_msg=str(err), attempts=attempts)

    def stop(self):
        self.running = False
