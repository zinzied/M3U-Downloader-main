import sys
from PyQt6.QtWidgets import QApplication
from gui import M3UDownloaderGUI

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = M3UDownloaderGUI()
    window.show()
    sys.exit(app.exec())
