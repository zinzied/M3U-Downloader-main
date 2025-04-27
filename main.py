import sys
from PyQt6.QtWidgets import QApplication
from gui import M3UDownloaderGUI

if __name__ == "__main__":
    # Create QApplication instance first
    app = QApplication(sys.argv)

    # Then create the main window
    window = M3UDownloaderGUI()
    window.show()

    # Start the event loop
    sys.exit(app.exec())
