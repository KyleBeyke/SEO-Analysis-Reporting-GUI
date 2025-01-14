import os
import pandas as pd

class ReportGenerator:
    """Utility class for generating and saving SEO analysis reports."""

    @staticmethod
    def save_csv(report_data, output_dir, file_name):
        """Save the report as a CSV file."""
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        file_path = os.path.join(output_dir, file_name)
        df = pd.DataFrame(report_data)
        df.to_csv(file_path, index=False)
        return file_path

    @staticmethod
    def save_html(report_data, output_dir, file_name):
        """Save the report as an HTML file."""
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        file_path = os.path.join(output_dir, file_name)
        df = pd.DataFrame(report_data)
        df.to_html(file_path, index=False)
        return file_path

    @staticmethod
    def generate_summary(report_data):
        """Generate a textual summary of the report."""
        total_urls = len(report_data)
        average_score = sum(item.get('Score', 0) for item in report_data) / total_urls
        return f"Total URLs: {total_urls}\nAverage SEO Score: {average_score:.2f}"

# Example usage (for testing purposes):
if __name__ == "__main__":
    sample_data = [
        {"URL": "https://example.com", "Score": 90},
        {"URL": "https://example.com/page", "Score": 85},
    ]
    generator = ReportGenerator()
    output_csv = generator.save_csv(sample_data, "./reports", "report.csv")
    output_html = generator.save_html(sample_data, "./reports", "report.html")
    print(f"CSV saved to {output_csv}")
    print(f"HTML saved to {output_html}")
    print(generator.generate_summary(sample_data))
