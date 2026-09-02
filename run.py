import sys
import logging
from http.server import ThreadingHTTPServer
from src.config import Config
from src.database.connection import initialize_database
from src.server.router import Router
from src.services.agent import agent_instance

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("run")

def main():
    logger.info("Starting Resume Parser Application...")
    
    # 1. Validate configuration
    try:
        Config.validate()
        logger.info("Configuration validated successfully.")
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
        
    # Validate Skill Registry
    try:
        from src.services.skills_registry import validate_registry
        validate_registry()
        logger.info("Skill registry validated successfully.")
    except ValueError as e:
        logger.error(f"Skill registry validation failed: {e}")
        sys.exit(1)

    # Validate Skill Relationships
    try:
        from src.services.skills_relationship import validate_relationships
        validate_relationships()
        logger.info("Skill relationships validated successfully.")
    except ValueError as e:
        logger.error(f"Skill relationships validation failed: {e}")
        sys.exit(1)

    # Validate Capability Graph
    try:
        from src.services.capability_graph import validate_capability_graph
        validate_capability_graph()
        logger.info("Capability graph validated successfully.")
    except ValueError as e:
        logger.error(f"Capability graph validation failed: {e}")
        sys.exit(1)


    # 2. Initialize database
    try:
        initialize_database()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)
        
    # Start background agent
    logger.info("Starting autonomous background job matching agent...")
    agent_instance.start()

    # Start background application worker
    logger.info("Starting background application worker...")
    from src.workers.application_worker import ApplicationWorker
    app_worker = ApplicationWorker(interval_seconds=5.0)
    app_worker.start()
        
    # 3. Start Web Server
    server_address = (Config.HOST, Config.PORT)
    httpd = ThreadingHTTPServer(server_address, Router)
    logger.info(f"Server running at http://{Config.HOST}:{Config.PORT}/")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
    finally:
        agent_instance.stop()
        app_worker.stop()
        httpd.server_close()
        logger.info("Server stopped.")

if __name__ == "__main__":
    main()
