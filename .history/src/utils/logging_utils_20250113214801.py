import logging
import os
from datetime import datetime


class LoggingSetup:
    """
    Configures and initializes logging for the project.
    """

    DEFAULT_LOG_DIR = "logs"
    DEFAULT_LOG_LEVEL = logging.INFO

    def __init__(self, log_dir=None, log_level=None):
        """
        Initializes the logging configuration.

        :param log_dir: Directory where log files are stored (default: `logs`).
        :param log_level: Logging level (default: `logging.INFO`).
        """
        self.log_dir = log_dir or self.DEFAULT_LOG_DIR
        self.log_level = log_level or self.DEFAULT_LOG_LEVEL

        # Ensure the log directory exists
        os.makedirs(self.log_dir, exist_ok=True)

        # Set up the logger
        self.logger = logging.getLogger("SEOAnalyzer")
        self.logger.setLevel(self.log_level)

        # Prevent duplicate handlers if already configured
        if not self.logger.handlers:
            self._setup_handlers()

    def _setup_handlers(self):
        """
        Sets up console and file handlers for logging.
        """
        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # File Handler
        log_file = os.path.join(self.log_dir, f"seo_analyzer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(self.log_level)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        self.logger.info("Logging setup complete. Logs will be stored in %s", self.log_dir)

    def get_logger(self):
        """
        Returns the configured logger instance.
        """
        return self.logger


# Singleton instance for global usage
def get_global_logger(log_dir=None, log_level=None):
    """
    Provides a global logging instance.

    :param log_dir: Optional log directory.
    :param log_level: Optional logging level.
    :return: Configured logger instance.
    """
    return LoggingSetup(log_dir, log_level).get_logger()
