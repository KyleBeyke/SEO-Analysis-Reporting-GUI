import sys
from PyQt5.QtWidgets import QApplication
from main_window import MainWindow  # Importing the updated MainWindow class

def main():
    """Main function to launch the SEO Analyzer application."""
    # Create the application
    app = QApplication(sys.argv)

    # Instantiate and show the main window
    window = MainWindow()
    window.show()

    # Execute the application
    sys.exit(app.exec_())

if __name__ == "__main__":
    print("Launching Advanced SEO Analyzer...")
    main()
