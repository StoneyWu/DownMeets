import os
import re
import sys
import yt_dlp
import requests
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

URL_FILE = "urls.txt"
OUTPUT_DIR = "meets"
COOKIES_FILE = "drive.google.com_cookies.txt"
MAX_WORKERS = 4
MAX_RETRIES = 3

def read_urls_from_file(file_path=URL_FILE):
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            f.write("# Add your Google Drive URLs here, one per line\n")
        print(f"{file_path} created. Add URLs and re-run the script.")
        return []
    with open(file_path, "r") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

def is_cookie_valid(urls, cookies_file=COOKIES_FILE):
    try:
        if not os.path.exists(cookies_file):
            print("⚠️  No cookies.txt file found.")
            return False
        if not urls:
            print("⚠️  URL list is empty. Please add at least one Drive link to urls.txt.")
            return False

        test_url = urls[0]
        print(f"🔍 Checking cookies.txt against: {test_url}")

        session = requests.Session()
        with open(cookies_file, 'r') as f:
            for line in f:
                if not line.startswith('#') and '\t' in line:
                    parts = line.strip().split('\t')
                    if len(parts) >= 7:
                        domain, _, path, secure, expiration, name, value = parts
                        session.cookies.set(name, value, domain=domain, path=path)

        response = session.get(test_url, allow_redirects=True)
        if "Sign in" in response.text or "accounts.google.com" in response.url:
            print("❌ Your cookies.txt file is either expired or invalid.")
            return False

        print("✅ Authentication successful — cookies.txt is valid.")
        return True
    except Exception as e:
        print(f"⚠️  Error checking cookie validity: {e}")
        return False

def clean_drive_filename(raw_title):
    raw_title = os.path.splitext(raw_title)[0]

    # Pattern 1: Remove "(2025-04-11 11:16 GMT+8)"
    match = re.search(r'\((\d{4})-(\d{2})-(\d{2}) \d{2}[:_]\d{2} (GMT|UTC)[^)]*\)', raw_title)
    if match:
        date = f"{match.group(1)}{match.group(2)}{match.group(3)}"
        title = re.sub(r'\s*\(\d{4}-\d{2}-\d{2} \d{2}[:_]\d{2} (GMT|UTC)[^)]*\)', '', raw_title).strip()
        return f"{date} - {title}.mp4"

    # Pattern 2: "Title - 2025_04_07 16_52 CST - Recording"
    match2 = re.search(r'^(.*?) - (\d{4})/(\d{2})/(\d{2}) \d{2}:\d{2} \w+(?: - Recording)?$', raw_title)
    if match2:
        title = match2.group(1).strip()
        date = f"{match2.group(2)}{match2.group(3)}{match2.group(4)}"
        return f"{date} - {title}.mp4"

    # Fallback
    today = datetime.now().strftime("%Y%m%d")
    return f"{today} - {raw_title.strip()}.mp4"

def download_with_ytdlp_and_rename(url, output_dir, cookies_file=COOKIES_FILE):
    ydl_opts = {
        'format': 'best',
        'cookiefile': cookies_file if os.path.exists(cookies_file) else None,
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'external_downloader': 'aria2c',
        'external_downloader_args': ['-x', '16', '-s', '16', '-k', '1M'],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except KeyboardInterrupt:
                print(f"\n🛑 Interrupted during download: {url}")
                raise

            actual_path = info['requested_downloads'][0]['filepath']
            raw_title = os.path.splitext(info.get('title', 'video'))[0]
            cleaned_filename = clean_drive_filename(raw_title)
            cleaned_filename = re.sub(r'[\\/*?:"<>|]', "_", cleaned_filename)
            new_path = os.path.join(output_dir, cleaned_filename)

            try:
                if Path(actual_path).resolve() != Path(new_path).resolve():
                    os.rename(actual_path, new_path)
                else:
                    print("⚠️  Skipping rename, paths are the same.")
                return new_path
            except FileExistsError:
                base, ext = os.path.splitext(new_path)
                new_path = f"{base}_1{ext}"
                os.rename(actual_path, new_path)
                return new_path

    except Exception as e:
        print(f"❌ yt-dlp failed for {url}: {e}")
        return None

def retry_download(url, output_dir):
    try:
        for attempt in range(MAX_RETRIES):
            print(f"🔁 Attempt {attempt + 1} for: {url}")
            result = download_with_ytdlp_and_rename(url, output_dir)
            if result:
                return result
        return None
    except KeyboardInterrupt:
        print(f"🛑 User interrupted download: {url}")
        raise

def download_all_parallel(urls, output_dir=OUTPUT_DIR, max_workers=MAX_WORKERS):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(retry_download, url, output_dir) for url in urls]
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    print(f"✅ Downloaded: {result}")
                else:
                    print(f"❌ Failed.")
                results.append(result)
            except KeyboardInterrupt:
                print("\n🛑 Parallel downloads interrupted by user.")
                executor.shutdown(wait=False, cancel_futures=True)
                raise
    return results

def main():
    if len(sys.argv) > 1:
        url = sys.argv[1]
        if not is_cookie_valid([url]):
            print("🔄 Please export a fresh cookies.txt from your browser and try again.")
            sys.exit(1)
        Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        result = retry_download(url, OUTPUT_DIR)
        if result:
            print(f"✅ Downloaded: {result}")
        else:
            print("❌ Failed to download.")
        return

    urls = read_urls_from_file()
    if not urls:
        print("❌ No valid URLs found. Please add Google Drive links to urls.txt.")
        return
    if not is_cookie_valid(urls):
        print("🔄 Please export a fresh cookies.txt from your browser and try again.")
        sys.exit(1)

    try:
        download_all_parallel(urls)
    except KeyboardInterrupt:
        print("\n🛑 Download interrupted by user.")
        sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("🛑 Interrupted by user.")
        sys.exit(0)
