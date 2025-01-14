import sys
import os
import re
import time
import threading
import queue
import webbrowser
from datetime import datetime
from urllib.parse import urlparse
from collections import Counter
import multiprocessing
import logging

# For concurrency
from concurrent.futures import ThreadPoolExecutor, as_completed

# PyQt5
from PyQt5.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QThread
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit,
    QVBoxLayout, QPushButton, QWidget, QSpinBox,
    QMessageBox, QFileDialog, QProgressBar, QCheckBox,
    QHBoxLayout
)

# Minimal BFS placeholders (Selenium is not strictly shown but you can adapt)
# We'll assume you have your BFS concurrency or Selenium-based code
# For demonstration, we use a stub.

###############################################################################
# SCRAPER WORKER
###############################################################################
class ScraperWorker(QObject):
    """A stub worker that simulates BFS or site analysis with concurrency."""
    finished = pyqtSignal(str, str)     # Emitted when done, with (csv_file, html_file)
    error = pyqtSignal(str)             # Emitted on error
    statusUpdate = pyqtSignal(str)      # Emitted with status messages
    analysisProgress = pyqtSignal(int, int)  # (current, total)

    def __init__(self, domain, max_pages, driver_path, output_dir, site_password, pagespeed_api):
        super().__init__()
        self.domain = domain
        self.max_pages = max_pages
        self.driver_path = driver_path
        self.output_dir = output_dir
        self.site_password = site_password
        self.pagespeed_api = pagespeed_api
        self.logger = logging.getLogger("SEO_ANALYZER")

    @pyqtSlot()
    def run(self):
        try:
            self.logger.info(f"[WORKER] Starting BFS/Analysis for domain={self.domain}")
            self.statusUpdate.emit(f"Starting BFS for {self.domain}")

            # For demonstration, pretend we discover or process pages
            time.sleep(1)

            # We'll produce a few debug lines to see if they appear in the file
            self.logger.debug("[WORKER] BFS simulation: discovered 5 pages.")
            # Simulate an error or an NLTK corpus load error
            # We'll just log an error for demonstration:
            self.logger.error("[WORKER] Simulated NLTK or BFS error - demonstration only.")

            # Final
            csv_file = os.path.join(self.output_dir, "demo_report.csv")
            html_file = os.path.join(self.output_dir, "demo_report.html")
            self.logger.info(f"[WORKER] BFS done. CSV => {csv_file}, HTML => {html_file}")

            # Emulate writing CSV/HTML
            with open(csv_file, "w") as f:
                f.write("demo csv content\n")
            with open(html_file, "w") as f:
                f.write("<html><body>demo html content</body></html>")

            self.logger.info("[WORKER] Emit finished signal.")
            self.finished.emit(csv_file, html_file)

        except Exception as e:
            self.logger.exception(f"[WORKER] Exception: {e}")
            self.error.emit(str(e))


###############################################################################
# MAIN WINDOW
###############################################################################
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BeykeTechnik SEO Analyzer (Debug Edition)")
        self.resize(500, 500)

        # Domain
        self.domain_label = QLabel("Domain / URL:")
        self.domain_input = QLineEdit("example.com")

        # Password
        self.protected_check = QCheckBox("Password protected?")
        self.protected_check.stateChanged.connect(self.on_protected_toggled)
        self.password_label = QLabel("Password:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_label.setVisible(False)
        self.password_input.setVisible(False)

        self.password_show_btn = QPushButton("Show")
        self.password_show_btn.setCheckable(True)
        self.password_show_btn.clicked.connect(self.toggle_password_visibility)
        self.password_show_btn.setVisible(False)

        # PageSpeed
        self.pagespeed_label = QLabel("PageSpeed API Key:")
        self.pagespeed_input = QLineEdit("AIzaSyB8R9HLyxA6cvv2PLzhh4fWXxlXlSopnpg")
        self.pagespeed_input.setEchoMode(QLineEdit.Password)
        self.pagespeed_show_btn = QPushButton("Show")
        self.pagespeed_show_btn.setCheckable(True)
        self.pagespeed_show_btn.clicked.connect(self.toggle_pagespeed_visibility)

        # Max Pages
        self.max_pages_label = QLabel("Max Pages (up to 999):")
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 999)
        self.max_pages_spin.setValue(10)

        # ChromeDriver
        self.driver_path_label = QLabel("ChromeDriver Path (optional):")
        self.driver_path_input = QLineEdit("/usr/local/bin/chromedriver")

        # Output
        self.output_dir_label = QLabel("Output Directory:")
        self.output_dir_button = QPushButton("Select...")
        self.output_dir_button.clicked.connect(self.select_output_directory)
        self.chosen_dir_label = QLabel(os.getcwd())

        # Enable logging
        self.enable_logging_check = QCheckBox("Enable Detailed Log File?")
        self.enable_logging_check.setChecked(False)

        # Start
        self.start_button = QPushButton("Start Analysis")
        self.start_button.clicked.connect(self.start_scraping)

        # Status & progress
        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignCenter)

        self.output_dir = os.getcwd()

        # Layout
        layout = QVBoxLayout()

        layout.addWidget(self.domain_label)
        layout.addWidget(self.domain_input)

        layout.addWidget(self.protected_check)
        layout.addWidget(self.password_label)
        pass_layout = QHBoxLayout()
        pass_layout.addWidget(self.password_input)
        pass_layout.addWidget(self.password_show_btn)
        layout.addLayout(pass_layout)

        layout.addWidget(self.pagespeed_label)
        ps_layout = QHBoxLayout()
        ps_layout.addWidget(self.pagespeed_input)
        ps_layout.addWidget(self.pagespeed_show_btn)
        layout.addLayout(ps_layout)

        layout.addWidget(self.max_pages_label)
        layout.addWidget(self.max_pages_spin)

        layout.addWidget(self.driver_path_label)
        layout.addWidget(self.driver_path_input)

        layout.addWidget(self.output_dir_label)
        layout.addWidget(self.output_dir_button)
        layout.addWidget(self.chosen_dir_label)

        layout.addWidget(self.enable_logging_check)

        layout.addWidget(self.start_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.scraper_thread = None

    def on_protected_toggled(self, state):
        if state == Qt.Checked:
            self.password_label.setVisible(True)
            self.password_input.setVisible(True)
            self.password_show_btn.setVisible(True)
        else:
            self.password_label.setVisible(False)
            self.password_input.setVisible(False)
            self.password_show_btn.setVisible(False)

    def toggle_password_visibility(self):
        if self.password_show_btn.isChecked():
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.password_show_btn.setText("Hide")
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.password_show_btn.setText("Show")

    def toggle_pagespeed_visibility(self):
        if self.pagespeed_show_btn.isChecked():
            self.pagespeed_input.setEchoMode(QLineEdit.Normal)
            self.pagespeed_show_btn.setText("Hide")
        else:
            self.pagespeed_input.setEchoMode(QLineEdit.Password)
            self.pagespeed_show_btn.setText("Show")

    def select_output_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_dir = folder
            self.chosen_dir_label.setText(folder)

    def start_scraping(self):
        # Force remove any existing root handlers (to ensure we can re-configure)
        for h in logging.root.handlers[:]:
            logging.root.removeHandler(h)

        # If Python >= 3.8, you can forcibly override with force=True. We'll do a try:
        # If user doesn't have 3.8, the except block uses old approach
        log_file = os.path.join(self.output_dir, "seo_analysis.log")
        try:
            if self.enable_logging_check.isChecked():
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[
                        logging.FileHandler(log_file, mode='w'),
                        logging.StreamHandler(sys.stdout)
                    ],
                    force=True
                )
                logging.info("Detailed logging to file enabled. (force=True approach)")
            else:
                logging.basicConfig(
                    level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)],
                    force=True
                )
                logging.warning("Minimal logging => console only. (force=True approach)")
        except TypeError:
            # If Python < 3.8, force=True is not available, fallback
            if self.enable_logging_check.isChecked():
                logging.basicConfig(
                    level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[
                        logging.FileHandler(log_file, mode='w'),
                        logging.StreamHandler(sys.stdout)
                    ]
                )
                logging.info("Detailed logging to file enabled. (no force=True fallback)")
            else:
                logging.basicConfig(
                    level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)]
                )
                logging.warning("Minimal logging => console only. (no force=True fallback)")

        logging.info("TEST: Logging is configured. This line must appear in seo_analysis.log if all is well.")
        logging.info(f"Active handlers right now: {logging.root.handlers}")

        self.start_button.setEnabled(False)
        self.status_label.setText("Initializing...")
        self.progress_bar.setRange(0, 0)

        domain = self.domain_input.text().strip()
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip()

        site_password = ""
        if self.protected_check.isChecked():
            site_password = self.password_input.text().strip()

        pagespeed_api = self.pagespeed_input.text()

        logging.info(f"start_scraping invoked from GUI. Domain={domain}, MaxPages={max_pages}, "
                     f"DriverPath={driver_path}, PasswordLen={len(site_password)}, "
                     f"PageSpeedKeyLen={len(pagespeed_api)}")

        self.scraper_thread = QThread()
        self.worker = ScraperWorker(
            domain, max_pages, driver_path, self.output_dir,
            site_password, pagespeed_api
        )
        self.worker.moveToThread(self.scraper_thread)

        self.scraper_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_scraper_finished)
        self.worker.error.connect(self.on_scraper_error)
        self.worker.statusUpdate.connect(self.on_status_update)
        self.worker.analysisProgress.connect(self.on_analysis_progress)

        self.worker.finished.connect(self.scraper_thread.quit)
        self.worker.error.connect(self.scraper_thread.quit)
        self.scraper_thread.finished.connect(self.cleanup_after_scraping)

        self.scraper_thread.start()

    @pyqtSlot(int, int)
    def on_analysis_progress(self, current_val, total_val):
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, total_val)
        self.progress_bar.setValue(current_val)

    @pyqtSlot(str, str)
    def on_scraper_finished(self, csv_file, html_file):
        logging.info("Scraper finished -> on_scraper_finished triggered.")
        QMessageBox.information(
            self,
            "Success",
            f"Report generated!\nCSV: {csv_file}\nHTML: {html_file}"
        )
        webbrowser.open(html_file)
        self.status_label.setText("Process complete. Ready for another run.")
        self.progress_bar.setValue(self.progress_bar.maximum())

    @pyqtSlot(str)
    def on_scraper_error(self, error_msg):
        logging.error(f"on_scraper_error: {error_msg}")
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.status_label.setText("Error. Check logs or try again.")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)

    @pyqtSlot()
    def cleanup_after_scraping(self):
        logging.info("cleanup_after_scraping called.")
        self.scraper_thread = None
        self.worker = None
        self.start_button.setEnabled(True)

    @pyqtSlot(str)
    def on_status_update(self, message):
        logging.info(f"statusUpdate: {message}")
        self.status_label.setText(message)

###############################################################################
# MAIN
###############################################################################
if __name__ == "__main__":
    # A small line to see if logging might do something before start_scraping
    # Typically, we won't see this in the file if we haven't set up logging yet.
    print("MAIN: Launching BeykeTechnik SEO Analyzer.")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
