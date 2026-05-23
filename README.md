# SEO Analysis and Reporting GUI

A Python SEO analysis tool with both a PyQt desktop interface and a command-line sitemap reporting workflow.

The application can crawl sitemap URLs, collect on-page SEO signals, and export report files for review. The GUI is useful for manual analysis sessions, while the CLI entry point is useful for repeatable sitemap runs.

## Features

- PyQt5 desktop interface for starting SEO analysis runs.
- Sitemap parsing and URL filtering.
- Page-level checks for titles, meta descriptions, headings, word counts, and keyword signals.
- CSV/HTML report generation.
- Optional Google PageSpeed API integration.
- Threaded worker utilities for longer crawls.

## Repository Layout

```text
SEO-Analysis-Reporting-GUI/
├── main.py                 # GUI launcher
├── src/
│   ├── core/               # Page analysis and worker logic
│   ├── gui/                # PyQt interface
│   ├── parsers/            # Sitemap and robots helpers
│   └── utils/              # Reporting, logging, URL, and text utilities
├── scripts/
│   └── validate.sh         # Lightweight repository validation
├── requirements.txt
└── README.md
```

## Setup

```bash
git clone https://github.com/KyleBeyke/SEO-Analysis-Reporting-GUI.git
cd SEO-Analysis-Reporting-GUI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run The GUI

```bash
python main.py
```

## Run From The CLI

```bash
python src/main.py https://example.com/sitemap.xml --base-domain example.com --output-dir reports
```

## Validate The Repository

```bash
scripts/validate.sh
```

The validation script compiles the source files and checks that committed generated artifacts have not crept back into the working tree.

## Generated Files

Keep local runtime output out of version control:

- `.venv/` or `venv/`
- `.history/`
- `.DS_Store`
- `*.log`
- `reports/`
- generated SEO report CSV/HTML files
- downloaded NLTK data

## License

This project is licensed under the terms in [LICENSE.txt](LICENSE.txt).
