import os
import argparse
import logging
from utils.url_manager import deduplicate_urls, filter_urls
from utils.sitemap_parser import SitemapParser
from utils.report_generator import ReportGenerator

def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("seo_analysis.log", mode="w"),
        ],
    )

def main():
    # Set up logging
    setup_logging()

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="SEO Analysis and Reporting Tool")
    parser.add_argument("sitemap_url", help="URL of the sitemap to process")
    parser.add_argument(
        "--output-dir",
        default=os.getcwd(),
        help="Directory to save the generated reports (default: current directory)",
    )
    parser.add_argument(
        "--base-domain",
        required=False,
        help="Filter URLs to keep only those within this base domain",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent threads or processes to use (default: 4)",
    )
    args = parser.parse_args()

    # Log input arguments
    logging.info(f"Starting analysis for sitemap: {args.sitemap_url}")
    logging.info(f"Output directory: {args.output_dir}")
    logging.info(f"Base domain filter: {args.base_domain}")
    logging.info(f"Concurrency level: {args.concurrency}")

    try:
        # Step 1: Fetch and parse sitemap
        parser = SitemapParser()
        raw_urls = parser.parse_sitemap(args.sitemap_url)
        logging.info(f"Fetched {len(raw_urls)} URLs from the sitemap")

        # Step 2: Deduplicate and filter URLs
        unique_urls = deduplicate_urls(raw_urls)
        if args.base_domain:
            filtered_urls = filter_urls(unique_urls, args.base_domain)
            logging.info(f"Filtered {len(filtered_urls)} URLs within domain {args.base_domain}")
        else:
            filtered_urls = unique_urls

        # Step 3: Generate SEO report
        report_gen = ReportGenerator(concurrency=args.concurrency)
        report_path = report_gen.generate_report(filtered_urls, args.output_dir)

        # Success message
        logging.info(f"SEO analysis completed. Report saved at: {report_path}")
        print(f"Report generated successfully: {report_path}")

    except Exception as e:
        logging.error(f"An error occurred during analysis: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
