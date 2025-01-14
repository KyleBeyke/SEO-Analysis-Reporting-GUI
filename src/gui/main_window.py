import os
import sys
import logging
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit, QVBoxLayout, QPushButton,
    QWidget, QSpinBox, QProgressBar, QCheckBox, QMessageBox, QFileDialog, QHBoxLayout
)

class MainWindow(QMainWindow):
    """Main application window for the SEO Analyzer GUI."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Advanced SEO Analyzer")
        self.resize(700, 600)

        # Input: Domain
        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("https://example.com")

        # Input: Max Pages
        self.max_pages_label = QLabel("Max Pages to Analyze:")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 999)
        self.max_pages_spin.setValue(10)

        # Input: ChromeDriver Path
        self.driver_path_label = QLabel("Path to ChromeDriver:")
        self.driver_path_input = QLineEdit("/usr/local/bin/chromedriver")

        # Input: PageSpeed API Key
        self.pagespeed_label = QLabel("Google PageSpeed API Key (Optional):")
        self.pagespeed_input = QLineEdit()
        self.pagespeed_input.setEchoMode(QLineEdit.Password)
        self.pagespeed_show_btn = QPushButton("Show")
        self.pagespeed_show_btn.setCheckable(True)
        self.pagespeed_show_btn.clicked.connect(self.toggle_pagespeed_visibility)

        # Output: Directory
        self.output_dir_label = QLabel("Output Directory:")
        self.output_dir_button = QPushButton("Select...")
        self.output_dir_button.clicked.connect(self.select_output_directory)
        self.chosen_dir_label = QLabel(os.getcwd())
        self.output_dir = os.getcwd()

        # Logging Option
        self.enable_logging_check = QCheckBox("Enable Detailed Logging")
        self.enable_logging_check.setChecked(True)

        # Start Button
        self.start_button = QPushButton("Start Analysis")
        self.start_button.clicked.connect(self.start_analysis)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        # Status Label
        self.status_label = QLabel("Status: Ready")
        self.status_label.setAlignment(Qt.AlignCenter)

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.domain_label)
        layout.addWidget(self.domain_input)
        layout.addWidget(self.max_pages_label)
        layout.addWidget(self.max_pages_spin)
        layout.addWidget(self.driver_path_label)
        layout.addWidget(self.driver_path_input)
        layout.addWidget(self.pagespeed_label)
        ps_layout = QHBoxLayout()
        ps_layout.addWidget(self.pagespeed_input)
        ps_layout.addWidget(self.pagespeed_show_btn)
        layout.addLayout(ps_layout)
        layout.addWidget(self.output_dir_label)
        layout.addWidget(self.output_dir_button)
        layout.addWidget(self.chosen_dir_label)
        layout.addWidget(self.enable_logging_check)
        layout.addWidget(self.start_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Threading
        self.scraper_thread = None

    @pyqtSlot()
    def start_analysis(self):
        """Start the scraping and analysis process."""
        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip()
        api_key = self.pagespeed_input.text().strip()

        # Configure logging
        self.configure_logging()

        # Validate inputs
        if not domain.startswith(("http://", "https://")):
            self.show_error("Invalid URL. Please include http:// or https://.")
            return

        # Disable Start Button
        self.start_button.setEnabled(False)
        self.status_label.setText("Initializing...")
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

        # Create and start the scraper worker thread
        self.scraper_thread = QThread()
        self.worker = ScraperWorker(
            base_url=domain,
            max_pages=max_pages,
            driver_path=driver_path,
            api_key=api_key
        )
        self.worker.moveToThread(self.scraper_thread)

        # Connect signals
        self.scraper_thread.started.connect(self.worker.start)
        self.worker.statusUpdate.connect(self.update_status)
        self.worker.analysisProgress.connect(self.update_progress)
        self.worker.finished.connect(self.on_analysis_complete)
        self.worker.error.connect(self.on_analysis_error)

        self.scraper_thread.start()

    def configure_logging(self):
        """Configure logging based on user preferences."""
        log_file = os.path.join(self.output_dir, "seo_analysis.log")
        level = logging.DEBUG if self.enable_logging_check.isChecked() else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
        )

    @pyqtSlot(str)
    def update_status(self, message):
        """Update the status label."""
        self.status_label.setText(message)

    @pyqtSlot(int, int)
    def update_progress(self, current, total):
        """Update the progress bar."""
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)

    @pyqtSlot(str, str)
    def on_analysis_complete(self, csv_file, html_file):
        """Handle successful analysis completion."""
        self.status_label.setText("Analysis complete!")
        self.start_button.setEnabled(True)
        QMessageBox.information(
            self,
            "Success",
            f"Analysis complete.\nCSV Report: {csv_file}\nHTML Report: {html_file}",
        )

    @pyqtSlot(str)
    def on_analysis_error(self, error_message):
        """Handle errors during analysis."""
        self.status_label.setText(f"Error: {error_message}")
        self.start_button.setEnabled(True)
        QMessageBox.critical(self, "Error", error_message)

    def select_output_directory(self):
        """Allow the user to select an output directory."""
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir = directory
            self.chosen_dir_label.setText(directory)

    def toggle_pagespeed_visibility(self):
        """Toggle visibility of the PageSpeed API key."""
        if self.pagespeed_show_btn.isChecked():
            self.pagespeed_input.setEchoMode(QLineEdit.Normal)
            self.pagespeed_show_btn.setText("Hide")
        else:
            self.pagespeed_input.setEchoMode(QLineEdit.Password)
            self.pagespeed_show_btn.setText("Show")

    def show_error(self, message):
        """Display an error message."""
        QMessageBox.critical(self, "Error", message)
