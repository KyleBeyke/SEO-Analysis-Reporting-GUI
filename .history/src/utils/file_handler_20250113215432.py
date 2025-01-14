import os
import csv
import pandas as pd
from datetime import datetime
import logging


class FileHandler:
    """
    A class for handling file operations such as saving CSV, HTML, and log files.
    """

    def __init__(self, output_dir=None):
        """
        Initializes the FileHandler with an output directory.

        :param output_dir: Path to the output directory. Defaults to the current working directory.
        """
        self.output_dir = output_dir or os.getcwd()
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _generate_file_path(self, base_name, extension):
        """
        Generates a file path with a timestamped name.

        :param base_name: Base name of the file (e.g., "report").
        :param extension: File extension (e.g., "csv").
        :return: Full file path with timestamp.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_base = "".join(c if c.isalnum() or c in "-_" else "_" for c in base_name)
        return os.path.join(self.output_dir, f"{sanitized_base}_{timestamp}.{extension}")

    def save_csv(self, data, base_name="report"):
        """
        Saves a list of dictionaries or a DataFrame to a CSV file.

        :param data: List of dictionaries or a pandas DataFrame.
        :param base_name: Base name for the file.
        :return: Path to the saved CSV file.
        """
        file_path = self._generate_file_path(base_name, "csv")
        try:
            if isinstance(data, pd.DataFrame):
                data.to_csv(file_path, index=False)
            elif isinstance(data, list):
                with open(file_path, mode="w", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=data[0].keys())
                    writer.writeheader()
                    writer.writerows(data)
            else:
                raise ValueError("Data must be a pandas DataFrame or a list of dictionaries.")
            logging.info(f"CSV saved: {file_path}")
        except Exception as e:
            logging.error(f"Failed to save CSV: {e}")
            raise
        return file_path

    def save_html(self, data, base_name="report"):
        """
        Saves a DataFrame to an HTML file.

        :param data: pandas DataFrame.
        :param base_name: Base name for the file.
        :return: Path to the saved HTML file.
        """
        file_path = self._generate_file_path(base_name, "html")
        try:
            if isinstance(data, pd.DataFrame):
                data.to_html(file_path, index=False)
            else:
                raise ValueError("Data must be a pandas DataFrame.")
            logging.info(f"HTML saved: {file_path}")
        except Exception as e:
            logging.error(f"Failed to save HTML: {e}")
            raise
        return file_path

    def configure_logging(self, log_file_name="app_log", level=logging.INFO):
        """
        Configures logging to save to a file and stream to the console.

        :param log_file_name: Base name for the log file.
        :param level: Logging level.
        :return: Path to the log file.
        """
        log_file_path = self._generate_file_path(log_file_name, "log")
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file_path, mode="a"),
                logging.StreamHandler(),
            ],
        )
        logging.info(f"Logging configured. Log file: {log_file_path}")
        return log_file_path


# Example Usage
if __name__ == "__main__":
    # Initialize the file handler
    file_handler = FileHandler(output_dir="output")

    # Example data
    sample_data = [
        {"Column1": "Value1", "Column2": "Value2"},
        {"Column1": "Value3", "Column2": "Value4"},
    ]
    sample_df = pd.DataFrame(sample_data)

    # Save CSV
    csv_path = file_handler.save_csv(sample_data, base_name="test_report")
    print(f"CSV saved at: {csv_path}")

    # Save HTML
    html_path = file_handler.save_html(sample_df, base_name="test_report")
    print(f"HTML saved at: {html_path}")

    # Configure logging
    log_path = file_handler.configure_logging(log_file_name="test_log")
    print(f"Log file configured at: {log_path}")
