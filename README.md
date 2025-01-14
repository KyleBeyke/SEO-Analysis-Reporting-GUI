# SEO Analysis and Reporting GUI

A powerful SEO analysis and reporting tool with a user-friendly GUI, leveraging advanced web scraping, page analysis, and reporting capabilities.

## Features

- **GUI Application**: Intuitive PyQt5-based interface for ease of use.
- **Page Analysis**: Extracts titles, meta descriptions, headings, word counts, keywords, and more.
- **Sitemap Crawling**: Gathers links from sitemaps or uses fallback BFS crawling.
- **PageSpeed Insights**: Integrates with Google's PageSpeed API for performance scores.
- **Keyword Analysis**: Tokenizes and stems text for advanced keyword extraction.
- **Multithreading and Multiprocessing**: Ensures efficient processing of multiple pages.
- **Export Reports**: Generates detailed CSV and HTML reports.

## Project Structure

SEO-Analysis-Reporting-GUI/
├── src/
│   ├── gui/                   # GUI-related components
│   ├── core/                  # Core application logic
│   ├── utils/                 # Utility modules
│   ├── tests/                 # Unit tests
├── assets/                    # Static files (e.g., icons, images)
├── requirements.txt           # Python dependencies
├── .gitignore                 # Files/directories to exclude from version control
├── README.md                  # Project documentation
├── LICENSE                    # License file
└── seo_analysis.log           # Log file (excluded via .gitignore)

## Installation

### Prerequisites

- Python 3.8+
- Pip (Python package installer)

### Steps

1. Clone the repository:
git clone https://github.com/your-username/SEO-Analysis-Reporting-GUI.git
cd SEO-Analysis-Reporting-GUI

2. Create and activate a virtual environment:
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

3. Install dependencies:
pip install -r requirements.txt

4. Launch the application:
python src/gui/main_window.py

## Usage

1. Open the application.
2. Enter the domain or URL for analysis.
3. Configure optional settings:
   - Password for protected pages.
   - PageSpeed API Key.
   - Maximum number of pages.
4. Click "Start Analysis" to begin.

## Contributing

1. Fork the repository.
2. Create a feature branch:
git checkout -b feature-name

3. Commit changes:
git commit -m "Description of changes"

4. Push to your branch:
git push origin feature-name

5. Submit a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Support

For questions or issues, please open an issue at https://github.com/your-username/SEO-Analysis-Reporting-GUI/issues.
