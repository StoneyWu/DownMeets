# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

DownMeets is a Python tool for automatically downloading Google Meet recordings stored on Google Drive, even when set to "view only" mode without direct download options.

## Core Architecture

### Technology Stack
- **Language**: Python 3.13+
- **Dependencies**: requests, tqdm, gdown, yt-dlp, taskipy
- **Package Management**: Poetry (with pyproject.toml configuration)
- **Download Method**: yt-dlp with aria2c external downloader for accelerated downloads

### Project Structure
- **download_meet.py** - Main script containing all download logic
- **urls.txt** - Input file containing Google Drive URLs (one per line)
- **meets/** - Output directory for downloaded videos
- **cookies.txt** - Browser cookies file for authentication
- **pyproject.toml** - Poetry configuration with dependencies and tasks

## Development Commands

### Essential Commands
```bash
# Install dependencies (requires Poetry)
poetry install

# Run the main script (using taskipy)
poetry run task run

# Run directly with Python
python download_meet.py

# Download single URL
python download_meet.py "https://drive.google.com/file/d/FILE_ID/view"

# Download multiple URLs from urls.txt
python download_meet.py
```

### Alternative without Poetry
```bash
# Install dependencies with pip
pip install requests tqdm gdown yt-dlp taskipy

# Run directly
python download_meet.py
```

## Core Architecture Patterns

### Download Strategy
The application uses yt-dlp as the primary download method:

1. **yt-dlp with Cookie Authentication**: Specialized video extractor that uses browser cookies to bypass Google Drive restrictions
2. **aria2c Integration**: External downloader for accelerated multi-connection downloads (16 connections)
3. **Retry Logic**: Automatic retry mechanism with configurable MAX_RETRIES=3

### Authentication System
- **Cookie-based Authentication**: Uses exported browser cookies from `cookies.txt` (or `drive.google.com_cookies.txt`)
- **Validity Checking**: Validates cookies before attempting downloads
- **Session Management**: Maintains authenticated sessions across requests

### Concurrent Processing
- **ThreadPoolExecutor**: Downloads multiple files in parallel (configurable MAX_WORKERS=4)
- **Retry Logic**: Automatic retry with configurable MAX_RETRIES=3
- **Progress Tracking**: Visual progress indicators for download status

### Filename Processing
- **Smart Parsing**: Extracts dates and meeting titles from Drive filenames
- **Pattern Recognition**: Handles multiple Google Meet filename formats
- **Sanitization**: Removes invalid filesystem characters
- **Conflict Resolution**: Automatically renames files to avoid overwrites

## Configuration

### Key Settings (download_meet.py:10-14)
```python
URL_FILE = "urls.txt"           # Input URLs file
OUTPUT_DIR = "meets"            # Download directory  
COOKIE_CANDIDATES = ["cookies.txt", "drive.google.com_cookies.txt"]  # Auth cookies
MAX_WORKERS = 4                 # Parallel download threads
MAX_RETRIES = 3                 # Retry attempts per URL
```

### Input Format (urls.txt)
- One Google Drive URL per line
- Comments start with # and are ignored
- Supports both file view URLs and direct share links

## Requirements

### System Dependencies
- Python 3.13+ (specified in pyproject.toml)
- aria2c (optional, for accelerated downloads via yt-dlp)

### Browser Setup
The tool requires exporting cookies from a logged-in Google Drive session:
1. Login to Google Drive in browser
2. Export cookies to `cookies.txt` (or `drive.google.com_cookies.txt`) (Netscape format)
3. Place file in project root directory

## Error Handling

### Authentication Flow
- Validates cookies before processing URLs
- Tests authentication against first URL in list
- Exits early if cookies are invalid/expired

### Download Resilience
- Implements retry logic for transient failures (up to MAX_RETRIES=3 attempts)
- Graceful handling of keyboard interrupts
- Detailed error reporting for debugging
- Parallel downloads with ThreadPoolExecutor (MAX_WORKERS=4)

## Development Notes

### External Downloader Integration
The yt-dlp configuration includes aria2c integration for faster downloads:
```python
'external_downloader': 'aria2c',
'external_downloader_args': ['-x', '16', '-s', '16', '-k', '1M']
```

### Browser Simulation
Uses specific User-Agent headers to avoid detection:
```python
'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
```

### Filename Cleaning Patterns
Implements regex patterns to parse Google Meet recording filenames:
- Pattern 1: `(2025-04-11 11:16 GMT+8)` format
- Pattern 2: `Title - 2025/04/07 16:52 CST - Recording` format
- Fallback: Uses current date with original title

## Troubleshooting

### Common Issues
- **Empty downloads**: Script will automatically retry up to MAX_RETRIES=3 times
- **Authentication errors**: Re-export fresh cookies.txt from browser
- **Invalid URLs**: Ensure URLs contain `/d/FILE_ID/` pattern
- **Permission errors**: Verify you have view access to the Google Drive file in your browser
- **aria2c not found**: Downloads will still work but may be slower without aria2c acceleration

### Cookie Management  
- Cookies expire and need periodic refresh
- Export from authenticated browser session
- Verify file format matches Netscape cookie standard