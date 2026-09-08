#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["yt-dlp>=2025.3.31"]
# ///
"""DownMeets — 下載 Google Drive 上設為「僅供檢視」的 Google Meet 錄影。

最省事的跑法（不用 clone、不用建虛擬環境）：

    uv run https://raw.githubusercontent.com/StoneyWu/DownMeets/customized/download_meet.py "網址"

影片會存到你執行指令時所在的目錄。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

SCRIPT_NAME = "download_meet.py"
REMOTE_URL = ("https://raw.githubusercontent.com/StoneyWu/DownMeets/"
              "customized/download_meet.py")
URL_FILE = "urls.txt"
COOKIE_CANDIDATES = ("cookies.txt", "drive.google.com_cookies.txt")
DEFAULT_BROWSER = ("chrome", None)
SUPPORTED_BROWSERS = (
    "brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale", "firefox", "safari",
)
MAX_RETRIES = 3
STALE_YTDLP_DAYS = 180
WORKERS_WITH_ARIA2C = 2
WORKERS_WITHOUT_ARIA2C = 4
ARIA2C_ARGS = ["-x", "16", "-s", "16", "-k", "1M"]
INVALID_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|%]')

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
                  "Gecko/20100101 Firefox/124.0",
}


# --------------------------------------------------------------------------
# 環境自檢
# --------------------------------------------------------------------------

def parse_browser_spec(value):
    """解析 --browser 的值，支援 yt-dlp 的「名稱:profile」語法。

    Chrome 有多個 profile 時，登入 Google 的往往不是 Default，
    只讀 Default 會拿到一堆無關 cookie，最後表現成 403。
    """
    name, _, profile = value.partition(":")
    name = name.strip().lower()
    if name not in SUPPORTED_BROWSERS:
        raise argparse.ArgumentTypeError(
            f"不支援的瀏覽器 {name!r}。可用：{'、'.join(SUPPORTED_BROWSERS)}")
    return (name, profile.strip() or None)


def describe_browser(spec):
    name, profile = spec
    return f"瀏覽器 {name}" + (f"（profile：{profile}）" if profile else "")


def list_browser_profiles(name):
    """列出這個瀏覽器有哪些 profile，讓使用者知道能指定什麼。"""
    try:
        from yt_dlp.cookies import _get_chromium_based_browser_settings
        browser_dir = Path(_get_chromium_based_browser_settings(name)["browser_dir"])
    except Exception:
        return []
    if not browser_dir.is_dir():
        return []
    return sorted(child.name for child in browser_dir.iterdir()
                  if child.is_dir() and (child / "Cookies").exists())


def script_reference():
    """提示訊息裡該怎麼稱呼這支腳本。

    從遠端 URL 執行時 uv 會把腳本存成隨機暫存檔名（download_meetXXXXXX.py），
    照著印對使用者沒有任何意義，這種情況改印原始的 raw URL——uv run 吃得下 URL。
    """
    return SCRIPT_NAME if Path(__file__).name == SCRIPT_NAME else REMOTE_URL


def invocation_hint():
    """可以直接複製貼上執行的完整指令前綴。"""
    return f"uv run {script_reference()}"


def package_install_hint(package):
    """依照這台機器實際有的套件管理器，回傳安裝指令。"""
    if sys.platform == "darwin":
        if shutil.which("brew"):
            return f"brew install {package}"
        return ('先安裝 Homebrew：/bin/bash -c "$(curl -fsSL '
                'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
    for manager, command in (
        ("apt-get", f"sudo apt-get install -y {package}"),
        ("dnf", f"sudo dnf install -y {package}"),
        ("pacman", f"sudo pacman -S {package}"),
        ("zypper", f"sudo zypper install -y {package}"),
    ):
        if shutil.which(manager):
            return command
    return f"請依你的系統套件管理器安裝 {package}"


def uv_install_hint():
    if sys.platform == "darwin" and shutil.which("brew"):
        return "brew install uv"
    return "curl -LsSf https://astral.sh/uv/install.sh | sh"


def report_missing_ytdlp():
    """yt-dlp 沒裝時，印出這台機器上實際可用的補救指令。"""
    command = invocation_hint()
    print("❌ 找不到 yt-dlp 模組，無法下載。\n")
    print("最省事（自動處理依賴，不用建虛擬環境）：")
    if shutil.which("uv"):
        print(f"    {command} \"網址\"\n")
    else:
        print(f"    {command} \"網址\"")
        print("  但你還沒有 uv，先裝：")
        print(f"    {uv_install_hint()}\n")
    print("或用現有的 Python 手動建環境：")
    print("    python3 -m venv .venv && .venv/bin/pip install yt-dlp")
    print(f"    .venv/bin/python {SCRIPT_NAME} \"網址\"")


def ytdlp_staleness(version):
    """yt-dlp 版本號就是發布日期（2026.08.19）。太舊的話 Google Drive
    extractor 多半已經失效，但使用者光看版本號看不出來。"""
    match = re.match(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})", version)
    if not match:
        return None
    try:
        days = (date.today() - date(*(int(g) for g in match.groups()))).days
    except ValueError:
        return None
    if days > STALE_YTDLP_DAYS:
        return f"已過 {days} 天，Google Drive extractor 可能失效"
    return None


def find_aria2c():
    return shutil.which("aria2c")


def run_environment_check(args):
    """--check：報告這次執行「實際會用到」的環境與設定，不下載任何東西。"""
    print(f"Python      : {sys.version.split()[0]}  ({sys.executable})")

    if yt_dlp is None:
        print("yt-dlp      : ❌ 未安裝")
    else:
        version = yt_dlp.version.__version__
        stale = ytdlp_staleness(version)
        if stale:
            print(f"yt-dlp      : ⚠️  {version}（{stale}）")
            print("              升級：uv 會自動用最新版；pip 的話 pip install -U yt-dlp")
        else:
            print(f"yt-dlp      : ✅ {version}")

    aria2c = find_aria2c()
    if aria2c:
        print(f"aria2c      : ✅ {aria2c}  （下載加速，{WORKERS_WITH_ARIA2C} 個平行任務）")
    else:
        print(f"aria2c      : ⚠️  未安裝，改用內建下載器（較慢，{WORKERS_WITHOUT_ARIA2C} 個平行任務）")
        print(f"              想加速：{package_install_hint('aria2')}")

    cookie_opts, cookie_description = resolve_cookie_source(args)
    icon = "📄" if "cookie 檔" in cookie_description else "🌐"
    print(f"cookie 來源 : {icon} {cookie_description}")
    browser = (cookie_opts.get("cookiesfrombrowser") or (None,))[0]
    if sys.platform == "darwin" and browser and browser != "firefox":
        print("              macOS 讀取時會跳出鑰匙圈授權視窗，請按「允許」")

    if yt_dlp is not None and cookie_opts.get("cookiefile"):
        try:
            print(f"cookie 有效期: {cookie_expiry_summary(load_cookiejar(cookie_opts))}")
        except Exception as error:
            print(f"cookie 有效期: ⚠️  讀取失敗（{error}）")

    print(f"輸出目錄    : 📁 {Path(args.output).expanduser().resolve()}")

    if yt_dlp is None:
        print()
        report_missing_ytdlp()
        return 1
    return 0


# --------------------------------------------------------------------------
# Cookie 來源
# --------------------------------------------------------------------------

def find_cookie_file(explicit_path):
    """依優先序找 cookie 檔：參數 > 環境變數 > 專案根目錄的慣用檔名。"""
    candidates = [explicit_path, os.environ.get("DOWNMEETS_COOKIES")]
    candidates.extend(COOKIE_CANDIDATES)
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def resolve_cookie_source(args):
    """決定要用哪個 cookie 來源，回傳 (ydl 參數, 給人看的描述)。

    優先序：--browser 明確指定 > cookie 檔 > 預設瀏覽器。
    """
    if args.browser:
        return {"cookiesfrombrowser": args.browser}, describe_browser(args.browser)

    cookie_file = find_cookie_file(args.cookies)
    if cookie_file:
        return {"cookiefile": cookie_file}, f"cookie 檔 {cookie_file}"

    return ({"cookiesfrombrowser": DEFAULT_BROWSER},
            describe_browser(DEFAULT_BROWSER) + "（預設）")


def announce_cookie_read(spec):
    """讀瀏覽器 cookie 前先講一聲。

    macOS 讀 Chrome 系瀏覽器會連跳兩個視窗，兩個都是針對 Chrome Safe Storage：
    一個是鑰匙圈項目的 ACL 授權（security 不在該項目的信任清單裡），另一個是
    因為 `security -w` 要輸出密碼明文而需要的確認。實測單獨執行
    `security find-generic-password -a Chrome -s "Chrome Safe Storage" -w`
    也會跳兩次，所以這是系統行為，不是程式重複讀取。
    """
    if sys.platform == "darwin" and spec and spec[0] != "firefox":
        print(f"🔓 正在讀取 {spec[0]} 的 cookie…")
        print("   macOS 會連跳兩次鑰匙圈視窗（一次授權存取項目、一次確認輸出明文），")
        print("   兩次都輸入你的 Mac 登入密碼，這是系統行為不是出錯。")
        print("   想一勞永逸：加上 --save-cookies 檔案，之後改用 --cookies 該檔案。")


def count_browser_cookies(spec):
    """讀一次瀏覽器 cookie，回傳 (google cookie 數, 錯誤訊息, cookiejar)。

    yt-dlp 讀不到時只會發一則 warning 然後用空的 cookie jar 繼續下去，
    最後表現成看不出原因的 HTTP 403。這裡主動先試一次，把原因講清楚。
    讀到的 jar 會一路傳下去重複使用——macOS 每讀一次就彈一次鑰匙圈。
    """
    announce_cookie_read(spec)
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(*spec[:2])
    except Exception as error:
        return 0, str(error), None
    return sum(1 for c in jar if "google" in (c.domain or "")), None, jar


def explain_browser_cookie_failure(spec, count, error):
    """瀏覽器 cookie 讀不到時的具體指引。"""
    browser, profile = spec
    print(f"\n❌ 從{describe_browser(spec)}讀不到 Google 的登入 cookie"
          + (f"（讀到 {count} 個）" if not error else "") + "。")
    if error:
        print(f"   原因：{error}")

    profiles = list_browser_profiles(browser)
    if profiles:
        print(f"\n   {browser} 上偵測到這些 profile：{'、'.join(profiles)}")
        if profile:
            print(f"   你指定的是「{profile}」——確認它在上面的清單裡，名稱要完全一致。")
        else:
            print("   預設只讀 Default。你登入 Google 的若是別的 profile，要指定它：")
        target = next((p for p in profiles if p != profile), profiles[0])
        print(f"       {invocation_hint()} --browser \"{browser}:{target}\" \"網址\"")

    if sys.platform == "darwin" and browser != "firefox":
        print("\n   macOS 讀取 Chrome 系瀏覽器需要解開登入鑰匙圈。")
        print("   跳出的視窗要的是你的「Mac 登入密碼」（開機解鎖用的那個），")
        print("   不是 Google 密碼。若輸入了卻一直不被接受，通常是改過系統密碼、")
        print("   但登入鑰匙圈還鎖在舊密碼上。先確認鑰匙圈密碼對不對：")
        print("       security unlock-keychain ~/Library/Keychains/login.keychain-db")
        print("   若這行也不接受你的密碼，就是鑰匙圈密碼不同步了。")

    print("\n   繞過去的方法：")
    step = 1
    if browser != "firefox":
        print(f"   {step}. 改用 Firefox（讀取不需要任何授權，前提是它有登入 Google）：")
        print(f"      {invocation_hint()} --browser firefox \"網址\"")
        step += 1
    print(f"   {step}. 匯出 cookie 檔（最可靠，完全不碰瀏覽器的金鑰保護）：")
    print("      瀏覽器裝「Get cookies.txt LOCALLY」擴充套件 → 登入 Google Drive")
    print("      → 匯出 drive.google.com 的 cookie（Netscape 格式）→ 存成 cookies.txt")
    print(f"      {invocation_hint()} --cookies cookies.txt \"網址\"")


def explain_cookie_failure(description, cookie_count=None):
    print("\n❌ 所有網址都讀取失敗，各自的錯誤訊息在上面。\n")

    if cookie_count:
        print(f"   cookie 讀取本身是成功的（{cookie_count} 個），所以問題不在 cookie。")
        print("   跑診斷可以直接看出是哪一層擋下來的：")
        print(f"       {invocation_hint()} --diagnose \"網址\"\n")
        print("   判讀方式：")
        print("     第 1 項 Drive 網頁版是 ❌  → 這個帳號看不到這支影片，程式無解")
        print("     第 4 項 get_video_info ❌  → 把它顯示的原因貼出來")
        return

    print(f"   若是驗證問題（目前用的是 {description}），可以試試：")
    print("  1. 確認該瀏覽器目前登入的帳號，看得到這支影片")
    if "瀏覽器" in description:
        if sys.platform == "darwin":
            print("  2. macOS 讀取 Chrome 系瀏覽器需要鑰匙圈授權，請在跳出的視窗按「允許」")
        print("  3. 換一個瀏覽器：--browser firefox（Firefox 不需要授權）")
    print("  4. 改用匯出的 cookie 檔：")
    print("     瀏覽器裝「Get cookies.txt LOCALLY」擴充套件 → 登入 Google Drive")
    print("     → 匯出 drive.google.com 的 cookie（Netscape 格式）→ 存成 cookies.txt")
    print("     然後加上 --cookies cookies.txt")


# --------------------------------------------------------------------------
# 檔名處理
# --------------------------------------------------------------------------

def parse_recording_name(raw_title):
    """從 Google Meet 錄影檔名拆出 (日期 YYYYMMDD 或 None, 會議標題)。"""
    title = os.path.splitext(raw_title)[0]

    # 「團隊會議 (2025-04-11 11:16 GMT+8)」
    match = re.search(
        r"\s*\((\d{4})-(\d{2})-(\d{2})\s+\d{2}[:_]\d{2}\s*(?:GMT|UTC)[^)]*\)\s*$",
        title)
    if match:
        return "".join(match.group(1, 2, 3)), title[:match.start()].strip()

    # 「團隊會議 - 2025/04/07 16:52 CST - Recording」
    match = re.search(
        r"\s*-\s*(\d{4})[/_-](\d{2})[/_-](\d{2})\s+\d{2}[:_]\d{2}\s+\w+"
        r"(?:\s*-\s*Recording)?\s*$",
        title)
    if match:
        return "".join(match.group(1, 2, 3)), title[:match.start()].strip()

    # 認不出格式就不編造日期，只保留原標題
    return None, title.strip()


def build_filename(raw_title, ext):
    """組出「20250411 - 團隊會議.mp4」；抽不到日期時只用標題。"""
    date, title = parse_recording_name(raw_title)
    stem = sanitize_filename(title)
    if date:
        stem = f"{date} - {stem}"
    return f"{stem}.{ext}"


def sanitize_filename(name):
    return INVALID_FILENAME_CHARS.sub("_", name).strip() or "video"


def next_available_path(path, taken):
    """找出「標題 (2).mp4」這種還沒被佔用的檔名。"""
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists() and candidate not in taken:
            return candidate
        index += 1


# --------------------------------------------------------------------------
# 同名衝突處理
# --------------------------------------------------------------------------

def ask_conflict_action(path, rename_target, remembered):
    """問使用者同名檔要怎麼處理，回傳 (動作, 是否套用到後續全部)。"""
    if remembered:
        return remembered, True

    if not sys.stdin.isatty():
        print(f"⏭️  已存在，跳過：{path.name}（非互動模式）")
        return "skip", False

    print(f"\n⚠️  檔案已存在：{path.name}")
    print(f"    [r] 改名（存成「{rename_target.name}」）  [o] 覆蓋  [s] 跳過")
    print("    大寫 R / O / S 表示後續全部都這樣處理")

    actions = {"r": "rename", "o": "overwrite", "s": "skip"}
    while True:
        choice = input("    請選擇 [r/o/s]： ").strip()
        action = actions.get(choice.lower())
        if action:
            return action, choice.isupper()
        print("    請輸入 r、o 或 s")


def plan_download(url, title, ext, output_dir, taken, remembered):
    """算出這支影片的目標路徑，必要時詢問衝突處理方式。

    回傳 (目標路徑或 None, 是否覆蓋, 新的記憶動作)。
    """
    filename = build_filename(title, ext)
    target = output_dir / filename

    if not target.exists() and target not in taken:
        return target, False, remembered

    rename_target = next_available_path(target, taken)
    action, remember = ask_conflict_action(target, rename_target, remembered)
    remembered = action if remember else remembered

    if action == "skip":
        return None, False, remembered
    if action == "overwrite":
        return target, True, remembered
    return rename_target, False, remembered


# --------------------------------------------------------------------------
# 診斷
# --------------------------------------------------------------------------

DRIVE_ORIGIN = "https://drive.google.com"
VIDEO_INFO_API = "https://drive.google.com/get_video_info?docid={id}"
PLAYBACK_API = ("https://content-workspacevideo-pa.googleapis.com/v1/drive/media"
                "/{id}/playback?key=AIzaSyDVQw45DwoYh632gvsP5vPDqEKvb-Ywnb8")


LOGIN_COOKIE_NAMES = ("SID", "__Secure-1PSID", "__Secure-3PSID",
                      "SAPISID", "HSID", "SSID")


def cookie_expiry_summary(jar):
    """回報登入用的關鍵 cookie 還有多久到期。

    使用者常擔心 cookie 很快失效，但 Google 的登入 cookie 多半是長效的。
    與其猜，直接把實際到期時間讀出來。
    """
    expiries = []
    session_only = []
    for cookie in jar or []:
        if cookie.name not in LOGIN_COOKIE_NAMES:
            continue
        if cookie.expires is None:
            session_only.append(cookie.name)
        else:
            expiries.append((cookie.expires, cookie.name))

    if not expiries:
        if session_only:
            return f"⚠️  {'、'.join(sorted(set(session_only)))} 是 session cookie，關掉瀏覽器就失效"
        return "⚠️  找不到登入用的 cookie（SID / SAPISID 等）"

    soonest, name = min(expiries)
    remaining = datetime.fromtimestamp(soonest) - datetime.now()
    when = datetime.fromtimestamp(soonest).strftime("%Y-%m-%d")
    if remaining.total_seconds() < 0:
        return f"❌ 已於 {when} 過期（{name}）"
    # 用四捨五入，不然 .days 會把「剩 3 天」截成 2 天
    days = round(remaining.total_seconds() / 86400)
    if days < 1:
        return f"⚠️  今天就會過期（{name}）"
    return f"最早到期的是 {name}，{when}（還有 {days} 天）"


def warn_if_git_tracked(path):
    """cookie 檔等同 Google 登入憑證，被 git 追蹤到就可能推上遠端。

    .gitignore 只擋固定的兩個檔名，換個名字存在 repo 裡就會被 git add -A
    掃進去。這個 repo 是公開的，推上去等於把登入狀態公諸於世。
    """
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path.parent, capture_output=True, text=True, timeout=5)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=path.parent, capture_output=True, timeout=5)
        if ignored.returncode == 0:
            return
    except (OSError, subprocess.SubprocessError):
        return

    print(f"\n🚨 {path} 在 git repo 裡而且沒有被 .gitignore 排除。")
    print("   這個檔案等同你的 Google 登入憑證，一旦 commit 並推上去，")
    print("   任何看得到那個 repo 的人都能存取你的 Drive。")
    print("   請改存到 repo 外面，例如：--save-cookies ~/.downmeets-cookies.txt")
    print("   或把檔名加進 .gitignore。\n")


def save_cookies_to(jar, destination):
    """把讀到的 cookie 另存一份，之後用 --cookies 就不必再過鑰匙圈。"""
    path = Path(destination).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        jar.save(str(path))
        path.chmod(0o600)
    except OSError as error:
        print(f"⚠️  cookie 存檔失敗 {path}：{error}")
        return
    print(f"💾 cookie 已存到 {path}（權限 600）")
    print(f"   有效期：{cookie_expiry_summary(jar)}")
    print(f"   下次改用這個就不必再過鑰匙圈：--cookies {path}")
    warn_if_git_tracked(path)


def materialize_cookies(jar, workdir):
    """把已經讀好的 cookie 存成暫存檔，之後全程用這個檔。

    否則每次建 YoutubeDL 實例都會重讀一次瀏覽器 cookie，macOS 上每讀一次
    就多彈一輪鑰匙圈。（注意單次讀取本來就會跳兩個視窗，那是系統行為，
    見 announce_cookie_read 的說明——別把它誤當成重複讀取。）
    """
    path = Path(workdir) / "cookies.txt"
    jar.save(str(path))
    path.chmod(0o600)
    return {"cookiefile": str(path)}


def load_cookiejar(cookie_opts):
    """把 cookie 來源轉成 cookiejar，診斷時要自己發請求。"""
    spec = cookie_opts.get("cookiesfrombrowser")
    if spec:
        announce_cookie_read(spec)
        from yt_dlp.cookies import extract_cookies_from_browser
        return extract_cookies_from_browser(*spec[:2])
    path = cookie_opts.get("cookiefile")
    if path:
        from yt_dlp.cookies import YoutubeDLCookieJar
        jar = YoutubeDLCookieJar(path)
        jar.load()
        return jar
    return None


def extract_file_id(url):
    match = re.search(r"/d/([\w-]+)", url)
    return match.group(1) if match else None


def parse_video_info(body):
    """解析 get_video_info 的回應（舊式 query string 格式）。

    成功時長這樣：status=ok&title=...&fmt_stream_map=22|https://...,18|https://...
    失敗時：status=fail&errorcode=150&reason=...
    """
    data = urllib.parse.parse_qs(body)
    if data.get("status", [""])[0] != "ok":
        return None, data.get("reason", ["未知原因"])[0]

    # fmt_list 形如 "22/1280x720,18/640x360"，用來挑畫質最高的 itag
    pixels = {}
    for entry in data.get("fmt_list", [""])[0].split(","):
        parts = entry.split("/")
        if len(parts) >= 2 and "x" in parts[1]:
            try:
                width, height = (int(n) for n in parts[1].split("x")[:2])
                pixels[parts[0]] = width * height
            except ValueError:
                continue

    streams = []
    for item in data.get("fmt_stream_map", [""])[0].split(","):
        itag, _, stream_url = item.partition("|")
        if stream_url:
            streams.append((pixels.get(itag, 0), itag, stream_url))
    if not streams:
        return None, "回應裡沒有可用的串流網址"

    streams.sort(reverse=True)
    return {"title": data.get("title", ["video"])[0],
            "itag": streams[0][1],
            "url": streams[0][2],
            "count": len(streams)}, None


def fetch_video_info(video_id, cookiejar):
    """走 drive.google.com 同網域的舊端點取得串流網址。

    yt-dlp 現在的 googledrive extractor 打的是 googleapis.com 的新 API，
    而 .google.com 的 cookie 依網域規則送不過去，對私有影片一律 403。
    這個舊端點是同網域，cookie 有效。
    """
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    request = urllib.request.Request(
        VIDEO_INFO_API.format(id=video_id),
        headers={**BROWSER_HEADERS, "Referer": f"{DRIVE_ORIGIN}/"})
    try:
        with opener.open(request, timeout=30) as response:
            return parse_video_info(response.read().decode("utf-8", "replace"))
    except Exception as error:
        return None, str(error)


def http_probe(opener, url, headers, limit=600):
    """發一個請求，回傳 (狀態碼, content-type, 內文摘要)。"""
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=30) as response:
            return (response.status, response.headers.get("Content-Type", ""),
                    response.read(limit).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        return (error.code, error.headers.get("Content-Type", ""),
                error.read(limit).decode("utf-8", "replace"))
    except Exception as error:
        return None, "", str(error)


def judge(status, content_type, body):
    """HTTP 200 不等於成功——Google 會用 200 回一個登入頁。"""
    if status != 200:
        return summarize_error(body)
    if "accounts.google.com" in body or "signin" in body[:400]:
        return "⚠️  被導向登入頁（等於失敗）"
    if content_type.startswith(("video/", "application/octet-stream")):
        return "🎯 拿到影片串流"
    if "application/json" in content_type:
        return "🎯 拿到 JSON metadata"
    return f"200（{content_type.split(';')[0] or '未知型別'}）"


def run_diagnosis(url, cookie_opts, save_cookies=None):
    """依序測試各個端點，指出哪條路通、問題出在哪一層。"""
    video_id = extract_file_id(url)
    if not video_id:
        print(f"❌ 網址裡找不到檔案 ID：{url}")
        return 1

    jar = load_cookiejar(cookie_opts)
    google_cookies = sum(1 for c in jar or [] if "google" in (c.domain or ""))
    if save_cookies and jar is not None:
        save_cookies_to(jar, save_cookies)
    print(f"檔案 ID     : {video_id}")
    print(f"cookie      : {google_cookies} 個 Google cookie")
    print(f"有效期      : {cookie_expiry_summary(jar)}")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = dict(BROWSER_HEADERS)

    print("\n端點測試：")

    status, ctype, body = http_probe(opener, f"{DRIVE_ORIGIN}/file/d/{video_id}/view", base)
    if status == 200 and "accounts.google.com" not in body:
        verdict = "✅ 這個帳號看得到這支影片"
    elif status == 200:
        verdict = "⚠️  被導向登入頁——cookie 沒生效"
    else:
        verdict = "❌ 這個帳號看不到（權限問題，程式無解）"
    print(f"  1. Drive 網頁版           : HTTP {status}  {verdict}")

    api = PLAYBACK_API.format(id=video_id)
    status, ctype, body = http_probe(opener, api, {**base, "Referer": f"{DRIVE_ORIGIN}/"})
    print(f"  2. playback API（無授權） : HTTP {status}  {judge(status, ctype, body)}")


    download_url = ("https://drive.usercontent.google.com/download"
                    f"?id={video_id}&export=download&confirm=t")
    status, ctype, body = http_probe(opener, download_url, base)
    print(f"  3. usercontent 下載端點   : HTTP {status}  {judge(status, ctype, body)}")

    info, error = fetch_video_info(video_id, jar)
    if info:
        print(f"  4. get_video_info（舊端點）: ✅ 拿到 {info['count']} 個串流"
              f"，最佳 itag {info['itag']}，標題「{info['title']}」")
        print("     🎯 這條路通——下載會自動走這裡")
    else:
        print(f"  4. get_video_info（舊端點）: ❌ {error}")

    print("\n把以上結果貼出來就能判斷問題出在哪一層。")
    return 0


def summarize_error(body):
    """從回應內文抓出重點，不要把整包 JSON 印出來。"""
    if not body:
        return ""
    for pattern in (r'"message":\s*"([^"]+)"', r'"reason":\s*"([^"]+)"',
                    r"<title>([^<]+)</title>"):
        match = re.search(pattern, body)
        if match:
            return match.group(1)[:120]
    return body.strip().replace("\n", " ")[:120]


# --------------------------------------------------------------------------
# 下載
# --------------------------------------------------------------------------

def build_ydl_opts(cookie_opts, use_aria2c):
    opts = {
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "http_headers": dict(BROWSER_HEADERS),
    }
    opts.update(cookie_opts)
    if use_aria2c:
        opts["external_downloader"] = "aria2c"
        opts["external_downloader_args"] = list(ARIA2C_ARGS)
    return opts


def probe(url, cookie_opts):
    """先抽 metadata 拿標題和副檔名，不下載。"""
    # 這裡刻意不設 no_warnings：yt-dlp 對 cookie 讀取失敗只發 warning，
    # 吞掉的話最後只會看到莫名其妙的 403
    opts = {**cookie_opts, "quiet": True,
            "noplaylist": True, "skip_download": True,
            "http_headers": dict(BROWSER_HEADERS)}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("title") or "video", info.get("ext") or "mp4"


def probe_all(urls, cookie_opts, workers):
    """取得每支影片的標題與下載來源。

    回傳 [(下載用網址, 標題, 副檔名) 或 None]。優先走 drive.google.com
    同網域的舊端點（cookie 有效），失敗才退回 yt-dlp 的 extractor。
    """
    jar = load_cookiejar(cookie_opts)

    def probe_one(url):
        video_id = extract_file_id(url)
        if video_id:
            info, error = fetch_video_info(video_id, jar)
            if info:
                return info["url"], info["title"], "mp4"
            print(f"ℹ️  舊端點取不到（{error}），改用 yt-dlp：{url}")
        try:
            title, ext = probe(url, cookie_opts)
            return url, title, ext
        except Exception as error:
            print(f"❌ 讀取失敗：{url}\n   {error}")
            return None

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(probe_one, urls))


def download(url, target, overwrite, base_opts):
    """下載單支影片到指定路徑，失敗會重試。"""
    # outtmpl 會做格式展開，路徑裡的 % 得跳脫（檔名的 % 已在 sanitize 時換掉，
    # 但輸出目錄是使用者給的，可能長成 ~/100%_backup）
    opts = {**base_opts, "outtmpl": {"default": str(target).replace("%", "%%")},
            "overwrites": True if overwrite else None}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
            return target
        except KeyboardInterrupt:
            raise
        except Exception as error:
            print(f"❌ 第 {attempt}/{MAX_RETRIES} 次失敗：{target.name}\n   {error}")
    return None


def download_all(jobs, base_opts, workers):
    """平行下載已規劃好的工作，回傳成功數。"""
    def run(job):
        url, target, overwrite = job
        result = download(url, target, overwrite, base_opts)
        if result:
            print(f"✅ 完成：{result.name}")
        return result

    succeeded = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run, job) for job in jobs]
        try:
            for future in futures:
                if future.result():
                    succeeded += 1
        except KeyboardInterrupt:
            # 已在執行的下載無法強制中斷（Python 執行緒的限制），只能取消還沒開始的
            print("\n🛑 已取消排隊中的下載，正在等進行中的結束…")
            executor.shutdown(wait=False, cancel_futures=True)
            raise
    return succeeded


# --------------------------------------------------------------------------
# 輸入來源
# --------------------------------------------------------------------------

def read_urls_from_file(file_path=URL_FILE):
    """讀取 urls.txt。檔案不存在時回傳空清單，不會擅自建檔。"""
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r", encoding="utf-8") as handle:
        return [line.strip() for line in handle
                if line.strip() and not line.startswith("#")]


def collect_urls(args):
    if args.urls:
        return args.urls
    urls = read_urls_from_file()
    if not urls:
        print("❌ 沒有指定網址。\n")
        print(f"  下載單支影片：{invocation_hint()} \"https://drive.google.com/file/d/檔案ID/view\"")
        print(f"  批次下載    ：把網址一行一個寫進 {URL_FILE}（# 開頭視為註解），再執行一次")
    return urls


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="下載 Google Drive 上設為「僅供檢視」的 Google Meet 錄影。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"沒給網址時會讀取當前目錄的 {URL_FILE}。影片預設存到當前目錄。",
    )
    parser.add_argument("urls", nargs="*", metavar="網址",
                        help="Google Drive 影片網址，可給多個")
    parser.add_argument("--browser", type=parse_browser_spec, metavar="名稱[:profile]",
                        help="從哪個瀏覽器讀取登入 cookie，預設 chrome。"
                             "多 profile 時可指定，例如 --browser \"chrome:Profile 1\"。"
                             f"可用：{'、'.join(SUPPORTED_BROWSERS)}")
    parser.add_argument("--cookies", metavar="檔案",
                        help="改用匯出的 Netscape 格式 cookie 檔")
    parser.add_argument("--output", metavar="目錄", default=".",
                        help="影片存放目錄（預設為當前目錄）")
    parser.add_argument("--save-cookies", metavar="檔案",
                        help="把這次讀到的瀏覽器 cookie 另存一份，之後改用 "
                             "--cookies 該檔案就不必再過鑰匙圈")
    parser.add_argument("--diagnose", action="store_true",
                        help="逐一測試 Google 各端點，找出 403 究竟卡在哪一層")
    parser.add_argument("--check", action="store_true",
                        help="只檢查執行環境，不下載")
    return parser.parse_args()


def main():
    with tempfile.TemporaryDirectory(prefix="downmeets-") as workdir:
        return run(parse_args(), workdir)


def run(args, workdir):

    if args.check:
        return run_environment_check(args)

    if yt_dlp is None:
        report_missing_ytdlp()
        return 1

    urls = collect_urls(args)
    if not urls:
        return 1

    if args.diagnose:
        cookie_opts, description = resolve_cookie_source(args)
        print(f"🔑 cookie 來源：{description}\n")
        return run_diagnosis(urls[0], cookie_opts, args.save_cookies)

    output_dir = Path(args.output).expanduser().resolve()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"❌ 無法建立輸出目錄 {output_dir}：{error}")
        return 1

    use_aria2c = find_aria2c() is not None
    workers = WORKERS_WITH_ARIA2C if use_aria2c else WORKERS_WITHOUT_ARIA2C
    cookie_opts, cookie_description = resolve_cookie_source(args)

    print(f"📁 輸出目錄：{output_dir}")
    print(f"🔑 cookie  ：{cookie_description}")
    if not use_aria2c:
        print(f"ℹ️  沒有 aria2c，改用內建下載器（較慢）。想加速：{package_install_hint('aria2')}")

    cookie_count = None
    spec = cookie_opts.get("cookiesfrombrowser")
    if spec:
        cookie_count, error, jar = count_browser_cookies(spec)
        if not cookie_count:
            explain_browser_cookie_failure(spec, cookie_count, error)
            return 1
        print(f"   （讀到 {cookie_count} 個 Google cookie）")
        if args.save_cookies:
            save_cookies_to(jar, args.save_cookies)
        # 存成暫存檔，後續全部用它，免得每個階段都再彈一次鑰匙圈
        cookie_opts = materialize_cookies(jar, workdir)

    print(f"🔍 讀取 {len(urls)} 支影片的資訊…")
    probed = probe_all(urls, cookie_opts, workers)

    if not any(probed):
        explain_cookie_failure(cookie_description, cookie_count)
        return 1

    jobs, taken, remembered = [], set(), None
    for item in probed:
        if item is None:
            continue
        url, title, ext = item
        target, overwrite, remembered = plan_download(
            url, title, ext, output_dir, taken, remembered)
        if target is None:
            continue
        taken.add(target)
        jobs.append((url, target, overwrite))

    if not jobs:
        print("沒有需要下載的項目。")
        return 0

    print(f"\n⬇️  開始下載 {len(jobs)} 支影片（{workers} 個平行任務）")
    succeeded = download_all(jobs, build_ydl_opts(cookie_opts, use_aria2c), workers)

    failed = len(jobs) - succeeded
    print(f"\n完成 {succeeded} 支" + (f"，失敗 {failed} 支" if failed else ""))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n🛑 已中斷")
        sys.exit(130)
