import logging
import os

def setup_logging(output_dir, enable_detailed_logging):
    """Configure logging for the application."""
    log_file = os.path.join(output_dir, "seo_analyzer.log")

    # Clear any existing root handlers to prevent duplicate logs
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    # Configure logging based on the detailed logging setting
    if enable_detailed_logging:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file, mode='w'),
                logging.StreamHandler()
            ],
            force=True  # Ensures existing handlers are overridden
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.StreamHandler()],
            force=True
        )

    logging.info("Logging initialized.")
    logging.info(f"Log file created at: {log_file}")
