# 📺 M3U Downloader Pro

A powerful, high-speed M3U playlist downloader with a user-friendly GUI interface. Specially designed for downloading VOD content and series from IPTV M3U playlists with support for authentication, token management, and advanced download features.

## ✨ Features

- 🚀 **Asynchronous Downloads**: Utilizes Python's asyncio for efficient concurrent downloads
- 🔥 **Chunked Downloading**: Downloads files in multiple chunks simultaneously for maximum speed
- ⏸️ **Resumable Downloads**: Continue interrupted downloads without starting over
- 🎬 **VOD Support**: Download movies and series with proper file extensions
- 🔐 **IPTV Authentication**: Handles token-based authentication and auto-refresh
- 📊 **Real-time Progress**: Live download speed and progress tracking
- 🛡️ **Anti-Ban Protection**: Smart rate limiting to avoid server bans
- 🎯 **Connection Pool Management**: Intelligent handling of concurrent connections
- 📱 **User-Friendly GUI**: Clean and intuitive interface built with PyQt6
- 🔄 **Auto-Retry**: Automatic retry on failed downloads or expired tokens
- 🛠️ **Customizable Settings**: Adjust concurrent downloads, chunks, and speed limits

## 🔧 Requirements

- Python 3.7+
- aiohttp
- aiofiles
- PyQt6 (for the GUI)

## 📥 Installation

1. Clone the repository:
```bash
git clone https://github.com/zinzied/m3u-Downloader.git
cd m3u-Downloader
```

2. Install dependencies:
```bash
pip install aiohttp aiofiles PyQt6
```

## 🖥️ Usage

1. Run the application:
```bash
python main.py
```

2. Using the GUI:
   - Load your M3U file containing VOD/Series links (`.m3u`, `.m3u8`) (Be sure that the Portal Works)
   - Select output directory for downloads
   - Configure download settings:
     - **Concurrent Downloads**: Number of files to download simultaneously (recommended: 2-3)
     - **Chunked Downloads**: Enable/disable splitting files into multiple chunks (faster downloads)
     - **Chunks per File**: Number of chunks to split each file into (recommended: 4-8)
     - **Speed Limit**: Optional limit to prevent bandwidth saturation
     - **Resume Downloads**: Enable/disable the ability to resume interrupted downloads
   - Select items to download or use "Download All"
   - Use "Resume Downloads" button to continue any previously interrupted downloads
   - Monitor real-time progress and speed in the interface

## 🧩 Key Components

### AsyncDownloader
- Handles asynchronous file downloads
- Supports chunked downloading for faster speeds
- Implements resumable downloads for interrupted transfers
- Manages IPTV authentication and token refresh
- Preserves original file extensions
- Real-time speed calculation and progress updates

### DownloadOptimizer
- Dynamically adjusts chunk sizes based on connection speed
- Implements adaptive rate limiting to prevent server bans
- Manages per-host connection limits for better server compatibility
- Provides token bucket algorithm for smooth downloads

### IPTVAuthenticator
- Handles token-based authentication
- Automatic token refresh on expiration
- Supports various IPTV provider APIs

### DownloadManager
- Manages concurrent downloads
- Controls chunked downloading settings
- Handles download state persistence for resuming
- Smart retry mechanism with exponential backoff
- Progress tracking and speed monitoring

### GUI Interface
- Clean and intuitive PyQt6-based design
- Configurable download settings
- Resume interrupted downloads with one click
- Real-time download speeds and progress tracking
- File extension preservation

## ✅ Supported Features

- ✅ VOD/Movie downloads
- ✅ Series/Episode downloads
- ✅ Token-based authentication
- ✅ Auto token refresh
- ✅ Chunked downloading (multi-part downloads)
- ✅ Resumable downloads (continue interrupted transfers)
- ✅ Adaptive rate limiting (prevent server bans)
- ✅ Real-time speed display
- ✅ Progress tracking
- ✅ Original file extensions
- ✅ Multiple concurrent downloads
- ✅ Server compatibility detection

## 🔧 Troubleshooting

Common issues and solutions:

- **458 Error**: Token expired - the app will automatically retry with a new token
- **Download Stuck**: Check internet connection and server availability
- **Wrong Extension**: File extensions are preserved from source URL
- **Server Doesn't Support Chunked Downloads**: The app will automatically detect this and fall back to single-chunk mode
- **Interrupted Downloads**: Use the "Resume Downloads" button to continue from where you left off
- **Slow Downloads**: Try enabling chunked downloading and increasing the number of chunks per file
- **Server Bans**: If you're getting banned, try enabling speed limits or disabling chunked downloads

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with Python's asyncio for high-performance async I/O
- Uses aiohttp for efficient HTTP requests
- PyQt6 for the modern user interface
- Implements best practices for IPTV content downloading
- Inspired by the need for reliable, resumable downloads
