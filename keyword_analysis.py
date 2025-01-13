import sys
import json
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit, QVBoxLayout, QPushButton,
    QWidget, QCheckBox, QFileDialog, QSpinBox, QMessageBox
)
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from bs4 import BeautifulSoup
from collections import Counter
import pandas as pd
import os
import re
from urllib.parse import urlparse
import webbrowser
import threading
from datetime import datetime

CONFIG_FILE = "config.json"
STOP_WORDS = {'the', 'and', 'is', 'in', 'it', 'to', 'for', 'with', 'on', 'this'}
IGNORED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".pdf", ".zip", ".exe")


def load_config():
    """Load configuration settings from a JSON file."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as file:
            return json.load(file)
    return {}


def save_config(config):
    """Save configuration settings to a JSON file."""
    with open(CONFIG_FILE, "w") as file:
        json.dump(config, file)


def is_valid_url(url):
    """Validate URL format."""
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


def sanitize_domain(domain):
    """Sanitize the domain name to create a safe file name."""
    return re.sub(r'[^a-zA-Z0-9]', '_', domain)


def append_https(domain):
    """Ensure the domain has https:// prefixed."""
    if not domain.startswith("https://"):
        return f"https://{domain}"
    return domain


def configure_driver(driver_path=None):
    """Configure and return a Selenium WebDriver."""
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(service=Service(driver_path or "/usr/local/bin/chromedriver"), options=options)


def scrape_links_with_selenium(driver, base_url, max_pages, status_callback):
    """Scrape internal links from the base URL."""
    update_status(status_callback, "Scraping links...")
    visited = set()
    to_visit = set([base_url])

    while to_visit and len(visited) < max_pages:
        current_url = to_visit.pop()
        if current_url in visited:
            continue

        try:
            driver.get(current_url)
            visited.add(current_url)
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href")
                if href and urlparse(href).netloc == urlparse(base_url).netloc:
                    if not href.endswith(IGNORED_EXTENSIONS):
                        to_visit.add(href)
        except Exception as e:
            print(f"Error scraping {current_url}: {e}")
    return visited


def clean_and_tokenize(text):
    """Tokenize and clean text."""
    text = text.lower()
    words = re.findall(r'\b[a-z]{3,}\b', text)
    return [word for word in words if word not in STOP_WORDS]


def calculate_seo_score(page_data):
    """Calculate SEO score based on adherence to best practices."""
    score = 100
    if not page_data["title"]:
        score -= 15  # Missing title
    elif page_data["title_length"] > 60 or page_data["title_length"] < 10:
        score -= 10  # Title too long or too short

    if not page_data["meta_desc"]:
        score -= 15  # Missing meta description
    elif page_data["meta_desc_length"] > 160 or page_data["meta_desc_length"] < 50:
        score -= 10  # Meta description too long or too short

    if page_data["missing_alt_count"] > 0:
        score -= 5  # Missing alt text for images

    if not page_data["canonical_url"]:
        score -= 5  # Missing canonical tag

    if not page_data["structured_data_present"]:
        score -= 10  # Missing structured data

    if page_data["h1_count"] == 0:
        score -= 10  # Missing H1 tags
    if page_data["h2_count"] == 0 and page_data["h3_count"] == 0:
        score -= 5  # Missing H2 and H3 tags

    if page_data["total_words"] > 0:
        if len(page_data["top_keywords"].split(", ")) < 5:
            score -= 5  # Low keyword variety

    return max(score, 0)  # Ensure the score does not go below 0


def generate_recommendations(page_data):
    """Generate actionable SEO recommendations based on the page data."""
    recommendations = []

    if not page_data["title"]:
        recommendations.append("Add a descriptive title (10-60 characters).")
    elif page_data["title_length"] > 60:
        recommendations.append("Shorten the title to 60 characters or fewer.")
    elif page_data["title_length"] < 10:
        recommendations.append("Lengthen the title to at least 10 characters.")

    if not page_data["meta_desc"]:
        recommendations.append("Add a meta description (50-160 characters).")
    elif page_data["meta_desc_length"] > 160:
        recommendations.append("Shorten the meta description to 160 characters or fewer.")
    elif page_data["meta_desc_length"] < 50:
        recommendations.append("Lengthen the meta description to at least 50 characters.")

    if page_data["missing_alt_count"] > 0:
        recommendations.append(f"Add alt attributes to {page_data['missing_alt_count']} image(s).")

    if not page_data["canonical_url"]:
        recommendations.append("Add a canonical tag to prevent duplicate content issues.")

    if not page_data["structured_data_present"]:
        recommendations.append("Add structured data (JSON-LD) for rich search results.")

    if page_data["h1_count"] == 0:
        recommendations.append("Add at least one `<h1>` tag to the page.")
    if page_data["h2_count"] == 0:
        recommendations.append("Add at least one `<h2>` tag to the page.")
    if page_data["h3_count"] == 0:
        recommendations.append("Add at least one `<h3>` tag to the page.")

    if page_data["total_words"] > 0:
        if len(page_data["top_keywords"].split(", ")) < 5:
            recommendations.append("Include more diverse keywords to improve content relevance.")

    return "; ".join(recommendations)


def analyze_page(driver, url, status_callback, current, total):
    """Analyze a single page for SEO metrics and generate recommendations."""
    update_status(status_callback, f"Analyzing page {current}/{total}: {url}")
    try:
        driver.get(url)
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Extract details
        title = soup.title.string.strip() if soup.title else None
        title_length = len(title) if title else 0
        meta_desc_tag = soup.find('meta', attrs={'name': 'description'})
        meta_desc = meta_desc_tag['content'].strip() if meta_desc_tag else None
        meta_desc_length = len(meta_desc) if meta_desc else 0
        content_text = soup.get_text(separator=" ").strip()
        words = clean_and_tokenize(content_text)
        total_words = len(words)
        keyword_counts = Counter(words)
        top_keywords = keyword_counts.most_common(10)
        images = soup.find_all('img')
        missing_alt = [img.get('src', 'Unknown Source') for img in images if not img.get('alt')]
        headings = {tag: len(soup.find_all(tag)) for tag in ['h1', 'h2', 'h3']}
        canonical_tag = soup.find('link', rel='canonical')
        canonical_url = canonical_tag['href'] if canonical_tag else None
        structured_data_present = bool(soup.find_all('script', type='application/ld+json'))

        page_data = {
            "url": url,
            "title": title,
            "title_length": title_length,
            "meta_desc": meta_desc,
            "meta_desc_length": meta_desc_length,
            "h1_count": headings.get('h1', 0),
            "h2_count": headings.get('h2', 0),
            "h3_count": headings.get('h3', 0),
            "total_words": total_words,
            "top_keywords": ", ".join([f"{kw} ({cnt}%)" for kw, cnt in top_keywords]),
            "missing_alt_count": len(missing_alt),
            "canonical_url": canonical_url,
            "structured_data_present": structured_data_present,
        }

        page_data["seo_score"] = calculate_seo_score(page_data)
        page_data["recommendations"] = generate_recommendations(page_data)
        return page_data
    except Exception as e:
        print(f"Error analyzing {url}: {e}")
        return {}


def generate_report(base_url, driver, max_pages, output_dir, status_callback):
    """Generate SEO report with analysis results."""
    links = scrape_links_with_selenium(driver, base_url, max_pages, status_callback)
    report_data = []
    total_links = len(links)
    domain_name = sanitize_domain(urlparse(base_url).netloc)
    current_date = datetime.now().strftime("%m%d%Y")

    for i, url in enumerate(links, start=1):
        report_data.append(analyze_page(driver, url, status_callback, i, total_links))

    update_status(status_callback, "Generating reports...")
    csv_file = os.path.join(output_dir, f"seo_report_{domain_name}_{current_date}.csv")
    html_file = os.path.join(output_dir, f"seo_report_{domain_name}_{current_date}.html")

    # Save reports
    df = pd.DataFrame(report_data)
    df.to_csv(csv_file, index=False)
    df.to_html(html_file, index=False)

    return csv_file, html_file


def update_status(callback, message):
    """Thread-safe status updates."""
    QMetaObject.invokeMethod(callback, "setText", Q_ARG(str, message))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BeykeTechnik SEO Report Generator")

 # Load saved configurations
        self.config = load_config()

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Domain:"))
        self.domain_input = QLineEdit()
        layout.addWidget(self.domain_input)

        self.password_checkbox = QCheckBox("Password Required")
        self.password_checkbox.stateChanged.connect(self.toggle_password_input)
        layout.addWidget(self.password_checkbox)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setEnabled(False)
        layout.addWidget(self.password_input)

        layout.addWidget(QLabel("Max Pages:"))
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 1000)
        self.max_pages_spin.setValue(50)
        layout.addWidget(self.max_pages_spin)

        layout.addWidget(QLabel("ChromeDriver Path:"))
        self.driver_path_input = QLineEdit()
        self.driver_path_input.setText(self.config.get("chromedriver_path", "/usr/local/bin/chromedriver"))
        layout.addWidget(self.driver_path_input)

        layout.addWidget(QLabel("Output Directory:"))
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setText(self.config.get("output_directory", ""))
        layout.addWidget(self.output_dir_input)

        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.select_output_directory)
        layout.addWidget(browse_button)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.start_button = QPushButton("Start Scraping")
        self.start_button.clicked.connect(self.start_scraping)
        layout.addWidget(self.start_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def toggle_password_input(self):
        self.password_input.setEnabled(self.password_checkbox.isChecked())

    def select_output_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_input.setText(directory)

    def update_status(self, message):
        self.status_label.setText(message)

    def start_scraping(self):
        domain = self.domain_input.text().strip()
        password_required = self.password_checkbox.isChecked()
        password = self.password_input.text().strip() if password_required else None
        max_pages = self.max_pages_spin.value()
        driver_path = self.driver_path_input.text().strip()
        output_dir = self.output_dir_input.text().strip()

        if not domain:
            QMessageBox.critical(self, "Error", "Domain cannot be empty.")
            return

        base_url = append_https(domain)
        if not is_valid_url(base_url):
            QMessageBox.critical(self, "Error", "Invalid domain format. Please enter a valid domain.")
            return

        if not output_dir:
            QMessageBox.critical(self, "Error", "Output directory cannot be empty.")
            return

        # Save the current configuration
        self.config["chromedriver_path"] = driver_path
        self.config["output_directory"] = output_dir
        save_config(self.config)

        def run_scraper():
            try:
                driver = configure_driver(driver_path)
                csv_file, html_file = generate_report(base_url, driver, max_pages, output_dir, self.status_label)
                driver.quit()
                self.update_status("Process complete. Ready for another run.")
                QMessageBox.information(self, "Success", f"Report generated!\nCSV: {csv_file}\nHTML: {html_file}")
                webbrowser.open(html_file)
            except Exception as e:
                self.update_status("Error occurred.")
                QMessageBox.critical(self, "Error", f"An error occurred: {e}")

        threading.Thread(target=run_scraper).start()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())