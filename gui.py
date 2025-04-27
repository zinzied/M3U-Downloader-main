from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, 
                            QFileDialog, QSpinBox, QGroupBox, QMessageBox, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPalette, QColor
import os
from typing import Dict, List, Optional
from m3u_parser import M3UParser, M3UEntry
from async_downloader import DownloadManager
from file_utils import ensure_unique_filename
from utils import get_extension_from_url, format_speed, format_status

class M3UDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("M3U Downloader")
        self.setMinimumSize(1200, 800)
        
        # Initialize managers
        self.download_manager = DownloadManager(max_concurrent=3)
        self.entries: List[M3UEntry] = []
        
        # Setup UI
        self.setup_gui()
        
    def setup_gui(self):
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # File Selection Group
        file_group = QGroupBox("File Selection")
        file_layout = QVBoxLayout(file_group)

        # M3U File selection
        m3u_frame = QFrame()
        m3u_layout = QHBoxLayout(m3u_frame)
        m3u_layout.setContentsMargins(0, 0, 0, 0)
        
        m3u_label = QLabel("M3U File:")
        self.m3u_path = QLineEdit()
        m3u_browse = QPushButton("Browse")
        m3u_browse.clicked.connect(self.browse_m3u)
        
        m3u_layout.addWidget(m3u_label)
        m3u_layout.addWidget(self.m3u_path)
        m3u_layout.addWidget(m3u_browse)
        
        # Output directory selection
        output_frame = QFrame()
        output_layout = QHBoxLayout(output_frame)
        output_layout.setContentsMargins(0, 0, 0, 0)
        
        output_label = QLabel("Output Directory:")
        self.output_dir = QLineEdit()
        output_browse = QPushButton("Browse")
        output_browse.clicked.connect(self.browse_output)
        
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_dir)
        output_layout.addWidget(output_browse)
        
        file_layout.addWidget(m3u_frame)
        file_layout.addWidget(output_frame)

        # Download Settings Group
        settings_group = QGroupBox("Download Settings")
        settings_layout = QHBoxLayout(settings_group)
        
        concurrent_label = QLabel("Concurrent Downloads:")
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(3)
        
        settings_layout.addWidget(concurrent_label)
        settings_layout.addWidget(self.concurrent_spin)
        settings_layout.addStretch()

        # Files List Group
        list_group = QGroupBox("Files to Download")
        list_layout = QVBoxLayout(list_group)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Title", "URL", "Status", "Speed"])
        self.tree.setColumnWidth(0, 350)
        self.tree.setColumnWidth(1, 450)
        self.tree.setColumnWidth(2, 100)
        self.tree.setColumnWidth(3, 100)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        
        list_layout.addWidget(self.tree)

        # Control Buttons
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        load_btn = QPushButton("Load M3U")
        download_selected_btn = QPushButton("Download Selected")
        download_all_btn = QPushButton("Download All")
        
        load_btn.clicked.connect(self.load_m3u)
        download_selected_btn.clicked.connect(self.download_selected)
        download_all_btn.clicked.connect(self.download_all)
        
        button_layout.addWidget(load_btn)
        button_layout.addWidget(download_selected_btn)
        button_layout.addWidget(download_all_btn)
        button_layout.addStretch()

        # Status Bar
        self.statusBar().showMessage("Ready")

        # Add all components to main layout
        main_layout.addWidget(file_group)
        main_layout.addWidget(settings_group)
        main_layout.addWidget(list_group)
        main_layout.addWidget(button_frame)

        # Style configuration
        self.apply_styles()

    def apply_styles(self):
        # Set modern style for buttons
        button_style = """
            QPushButton {
                padding: 8px 16px;
                background-color: #0078D4;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #106EBE;
            }
            QPushButton:pressed {
                background-color: #005A9E;
            }
        """
        
        # Set style for group boxes
        group_style = """
            QGroupBox {
                font-weight: bold;
                padding-top: 20px;
                margin-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """

        self.setStyleSheet(button_style + group_style)

    def browse_m3u(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select M3U File",
            "",
            "M3U Files (*.m3u);;All Files (*.*)"
        )
        if filename:
            self.m3u_path.setText(filename)

    def browse_output(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory"
        )
        if directory:
            self.output_dir.setText(directory)

    def load_m3u(self):
        m3u_file = self.m3u_path.text()
        if not m3u_file:
            QMessageBox.warning(self, "Error", "Please select an M3U file first")
            return

        try:
            self.entries = M3UParser.parse(m3u_file)
            self.tree.clear()
            for entry in self.entries:
                item = QTreeWidgetItem([entry.title, entry.url, "Pending", ""])
                self.tree.addTopLevelItem(item)
            self.statusBar().showMessage(f"Loaded {len(self.entries)} items")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def download_selected(self):
        selected_items = self.tree.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Info", "Please select items to download")
            return
        self._start_download(selected_items)

    def download_all(self):
        all_items = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        if not all_items:
            QMessageBox.information(self, "Info", "No items to download")
            return
        self._start_download(all_items)

    def _start_download(self, items):
        output_dir = self.output_dir.text()
        if not output_dir:
            QMessageBox.warning(self, "Error", "Please select an output directory")
            return

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        try:
            max_concurrent = self.concurrent_spin.value()
            self.download_manager = DownloadManager(max_concurrent=max_concurrent)
        except ValueError:
            QMessageBox.warning(self, "Error", "Invalid concurrent downloads value")
            return

        downloads = []
        for item in items:
            url = item.text(1)
            filename = f"{item.text(0)}{get_extension_from_url(url)}"
            filepath = ensure_unique_filename(output_dir, filename)
            downloads.append((url, filepath))
            item.setText(2, "Queued")
            item.setText(3, "")

        def update_progress(filename: str, progress: float, speed: Optional[str] = None):
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.text(0) == filename:
                    item.setText(2, format_status(progress))
                    if speed and progress < 100:
                        item.setText(3, speed)
                    elif progress >= 100:
                        item.setText(3, "")
                    break

        try:
            self.download_manager.start_downloads(downloads, progress_callback=update_progress)
            self.statusBar().showMessage("Downloading files...")
        except Exception as e:
            QMessageBox.critical(self, "Download Error", f"Failed to start downloads: {str(e)}")

    def closeEvent(self, event):
        self.download_manager.shutdown()
        event.accept()
