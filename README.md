# DownMeets

Tool for automatic download of Google Meet meeting videos stored on Google Drive.

## Overview

This project allows downloading Google Meet videos that have been shared on Google Drive, even when configured as "view only" and without a direct download option. It uses authentication cookies to bypass download restrictions and supports parallel downloads for multiple videos.

## Technique Used

This script is based on the technique described in the article:
[How to download Google Meet meeting recordings set to "view only" mode](https://dev.to/gabrieldiem/how-to-download-google-meet-meeting-recordings-set-to-view-only-mode-4d2a) by Gabriel Diem.

The technique consists of:

1. **Cookie-based Authentication**: Uses exported browser cookies from an authenticated Google Drive session to bypass download restrictions

2. **yt-dlp with aria2c**:
   - Uses yt-dlp specialized extractor for Google Drive videos
   - Leverages aria2c external downloader for accelerated downloads (16 connections)
   - Automatically handles video stream extraction

3. **Browser simulation**: Uses specific HTTP headers (Firefox User-Agent) to simulate a real browser

4. **Parallel downloads**: Supports downloading multiple videos simultaneously with configurable worker threads

## Requirements

- Python 3.13 or higher
- Poetry (for dependency management)
- aria2c (optional, for accelerated downloads)
- Browser cookies exported from Google Drive session

### Dependencies (managed by Poetry):
- requests (>=2.32.3)
- tqdm (>=4.67.1)
- gdown (>=5.2.0)
- yt-dlp (>=2025.3.31)
- taskipy (>=1.14.1)

### Installing aria2c (optional but recommended):

**macOS:**
```bash
brew install aria2
```

**Ubuntu/Debian:**
```bash
sudo apt-get install aria2
```

**Windows:**
Download from [aria2 GitHub releases](https://github.com/aria2/aria2/releases)

## Installation

1. **Install Poetry** (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. **Clone the repository and install dependencies**:
```bash
git clone <repository-url>
cd DownMeets
poetry install
```

3. **Export cookies from your browser**:
   - Install a browser extension like "Get cookies.txt LOCALLY" or "cookies.txt"
   - Login to Google Drive in your browser
   - Export cookies for `drive.google.com` in Netscape format
   - Save the file as `drive.google.com_cookies.txt` in the project root

## Usage

### To download a single URL:

```bash
poetry run python download_meet.py "https://drive.google.com/file/d/YOUR_FILE_ID/view"
```

Or using taskipy:
```bash
poetry run task run "https://drive.google.com/file/d/YOUR_FILE_ID/view"
```

### To download multiple URLs:

1. Add the URLs to the `urls.txt` file (one per line)
2. Execute:

```bash
poetry run python download_meet.py
```

Or using taskipy:
```bash
poetry run task run
```

## Configuration

The main settings are defined at the beginning of the `download_meet.py` file:

```python
# Configuration
URL_FILE = "urls.txt"           # File with URLs (one per line)
OUTPUT_DIR = "meets"            # Output directory for downloaded videos
COOKIES_FILE = "drive.google.com_cookies.txt"  # Browser cookies file
MAX_WORKERS = 4                 # Number of parallel download threads
MAX_RETRIES = 3                 # Number of retry attempts per URL
```

## Features

- **Cookie-based authentication**: Uses browser cookies to bypass download restrictions
- **Parallel downloads**: Download multiple videos simultaneously (configurable workers)
- **Automatic retry**: Retries failed downloads up to 3 times
- **Smart filename cleaning**: Automatically parses and standardizes Google Meet recording filenames
- **Accelerated downloads**: Uses aria2c with 16 connections for faster downloads
- **Duplicate handling**: Automatically renames files to avoid overwrites
- **Progress tracking**: Visual indicators for download progress and status
- **Keyboard interrupt handling**: Gracefully handles Ctrl+C interruptions

## How It Works

1. **Cookie Validation**:
   - Loads cookies from `drive.google.com_cookies.txt` (Netscape format)
   - Validates authentication by testing against the first URL
   - Ensures cookies are valid before starting downloads

2. **Download Process**:
   - Uses yt-dlp with cookie authentication to extract video streams
   - Leverages aria2c external downloader for accelerated multi-connection downloads
   - Automatically handles Google Drive video extraction

3. **Filename Processing**:
   - Parses Google Meet recording filenames (multiple format support)
   - Standardizes to format: `YYYYMMDD - Title.mp4`
   - Removes invalid filesystem characters
   - Handles duplicate filenames by appending numbers

4. **Parallel Execution**:
   - Uses ThreadPoolExecutor to download multiple videos simultaneously
   - Configurable worker threads (default: 4)
   - Automatic retry logic for failed downloads (up to 3 attempts)

## Why It Works

The technique works because Google Drive needs to deliver the video content to the browser for playback, even when the download option is disabled. By using authenticated browser cookies and yt-dlp:

1. **Authentication bypass**: Browser cookies contain valid session tokens that prove you have access to view the video
2. **Stream extraction**: yt-dlp identifies the streaming endpoints that the browser player uses
3. **Direct access**: Makes authenticated requests directly to video stream endpoints
4. **Local storage**: Saves the received video stream locally as an MP4 file

This method works even when Google Drive shows "Download options disabled" or "Download unavailable", since these restrictions are UI-level only, not enforced at the network/API level where the script operates.

## Troubleshooting

### Cookie Issues
- **"No cookies.txt file found"**: Export cookies from your browser and save as `drive.google.com_cookies.txt`
- **"Your cookies.txt file is either expired or invalid"**: Re-export fresh cookies from an authenticated browser session
- **Cookie format errors**: Ensure cookies are exported in Netscape format (not JSON)

### Download Issues
- **Empty downloads**: Script will automatically retry up to 3 times
- **"yt-dlp failed"**: Check if aria2c is installed, or the script will fall back to standard download
- **Incorrect URLs**: Ensure URL contains the file ID pattern: `https://drive.google.com/file/d/FILE_ID/view`
- **Permission errors**: Verify you have view access to the Google Drive video in your browser

### Other Issues
- **Parallel download problems**: Reduce `MAX_WORKERS` value in the script (default: 4)
- **Filename conflicts**: Script automatically appends `_1`, `_2`, etc. to duplicate filenames
- **Interrupted downloads**: Press Ctrl+C to gracefully stop; partial downloads will be retried on next run

## Output Format

Downloaded videos are saved with standardized filenames in the `meets/` directory:
- Format: `YYYYMMDD - Title.mp4`
- Example: `20250411 - Team Meeting.mp4`

Supported input filename patterns:
1. `Title (2025-04-11 11:16 GMT+8).mp4`
2. `Title - 2025/04/07 16:52 CST - Recording.mp4`
3. Fallback: Uses current date if pattern not recognized

## License

This project is provided as-is for educational purposes. Respect Google's Terms of Service and only download content you have permission to access.