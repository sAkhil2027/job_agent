import sys
import os
import logging
import uvicorn
from src.config import Config

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
    # Check CLI arguments
    if "--worker" in sys.argv:
        import worker
        worker.main()
        return

    logger.info("Starting Autonomous Job Matcher Application (FastAPI + Uvicorn)...")
    
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

    # Run Uvicorn ASGI server
    from src.server.app import app
    host = getattr(Config, "HOST", "0.0.0.0")
    port = int(getattr(Config, "PORT", 8000))
    logger.info(f"Launching Uvicorn server on http://{host}:{port}/")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )

if __name__ == "__main__":
    main()
