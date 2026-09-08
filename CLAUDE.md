# CLAUDE.md

這份檔案給 Claude Code (claude.ai/code) 在這個 repo 工作時參考。

## 專案概述

DownMeets 下載 Google Drive 上設為「僅供檢視」、沒有下載按鈕的 Google Meet 會議錄影。
整個工具就是一支腳本 `download_meet.py`。

## 最重要的架構限制：必須維持單檔

`download_meet.py` **必須是單一檔案、不能拆模組**。這是硬需求，不是風格偏好——
主要使用方式是直接從 GitHub raw URL 執行：

```bash
uv run https://raw.githubusercontent.com/StoneyWu/DownMeets/customized/download_meet.py "網址"
```

`uv run <URL>` 只會抓那一個檔案，一旦拆出 import 就整個壞掉。所以這裡刻意
違反「多個小檔優於單一大檔」的通則。要加功能請加在同一個檔案裡，
並注意控制檔案長度（目前約 450 行）。

## 依賴管理

依賴用 PEP 723 內嵌宣告在檔案開頭：

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["yt-dlp>=2025.3.31"]
# ///
```

`uv run` 讀這段自動建隔離環境。**唯一的 Python 依賴是 yt-dlp**，
不要為了小功能新增依賴——每多一個都會拖慢首次執行。

**`requires-python` 必須跟著 yt-dlp 的需求走，不是跟著腳本語法走。**
曾經寫成 `>=3.9`（因為腳本本身沒用到 3.10 語法），結果 yt-dlp 需要 `>=3.10`，
uv 在 3.9 環境下會沉默解析出快一年前的舊版 yt-dlp，Google Drive extractor
早就失效了卻沒有任何錯誤訊息。改動這行前先確認 yt-dlp 當前的 `requires_python`。

這個 repo **刻意不放 `pyproject.toml` 和 `poetry.lock`**——依賴只宣告在腳本檔頭這一處，
沒有第二個地方會不同步。不要為了「比較正式」而把它們加回來。

## 為什麼不用 yt-dlp 的 GoogleDrive extractor（重要，別走回頭路）

**yt-dlp 的 googledrive extractor 對「需要登入才看得到」的影片一律 403，
再多的 cookie 都沒用。** 排查花了很久，結論記在這裡，不要再試一次：

它打的是 `content-workspacevideo-pa.googleapis.com/v1/drive/media/{id}/playback`。
那是 **googleapis.com** 網域，而使用者的登入 cookie 在 **google.com** —— 不同的
註冊網域，cookie 依規則不會被帶過去。決定性證據：完全不帶 cookie 打那個端點，
拿到的錯誤與帶著 165 個 cookie 時**逐字相同**（`USER_PERMISSION_DENIED`）。

已經試過而且**確定無效**的方向：

- **SAPISIDHASH 授權標頭**：Google 跨網域 API 的標準機制，但這個端點回 401。
  另外只要送 `X-Origin` 就會先觸發 XD3 檢查而 400，連驗證都到不了。
- **`authuser` / `X-Goog-AuthUser`**：網址若含 `/u/N/` 理論上該指定帳號，
  但實測對私有影片無效。
- **`drive.usercontent.google.com/download`**：對「僅供檢視」的檔案回登入頁。

**可行的路徑是 `https://drive.google.com/get_video_info?docid={id}`** —— 舊端點，
但還活著，而且就在 `drive.google.com` 底下，cookie 有效。回應是舊式 query string
（`status=ok&fmt_stream_map=itag|url,...`），解析後拿最高畫質的串流網址下載。
`--diagnose` 保留了各端點的逐層測試，哪天這條也壞了可以快速定位。

## 核心流程

```
parse_args → 環境自檢 → 決定 cookie 來源 → 平行 probe 取得標題
           → 逐一規劃目標路徑（互動處理同名衝突）→ 平行下載
```

先 probe 再下載是刻意的：要先知道標題才能算出檔名，才能在**下載開始前**
把所有互動問完。否則平行下載時多個執行緒同時 `input()` 會打架。

## 設計決定（改動前請先讀）

- **輸出預設為當前目錄**，不是子目錄。使用者已經 `cd` 到想要的位置了。
- **不擅自建檔**。舊版找不到 `urls.txt` 會幫你建一個，在遠端一行執行的情境下
  等於在使用者目錄亂丟東西。現在是印用法就結束。
- **抽不到日期就不加日期前綴**。舊版 fallback 是 `datetime.now()`，
  等於幫三個月前的會議標上今天日期。不知道就不要編。
- **aria2c 用 `shutil.which` 偵測**，沒有就走 yt-dlp 內建下載器。
  有 aria2c 時平行數降到 2（它自己開 16 連線，再多會被 Google 限流）。
- **cookie 預設讀 Chrome**。macOS 上讀 Chrome 系瀏覽器會跳鑰匙圈授權視窗，
  這是系統擋的。不要為了避開它而自動輪詢多個瀏覽器——會連環彈視窗，體驗更差。
  讓使用者用 `--browser` 主動選擇。
- **檔名的 `%` 必須替換掉**。`outtmpl` 吃的是完整檔名，`%` 會被 yt-dlp
  當成格式指示符（「Q1 達成率 95%」這種標題就會出事）。輸出目錄的路徑也要
  跳脫，使用者可能 `cd` 到 `~/100%_backup`。
- **cookie 全程只讀一次**，存成權限 600 的暫存檔給後續階段用。每讀一次
  macOS 就彈一次鑰匙圈。注意 `security` 本身就會問兩次（一次 ACL 授權、
  一次確認輸出明文），那是系統行為不是程式重複讀取，別再去追。
- **cookie 檔等同登入憑證**。`--save-cookies` 會檢查目標是否在 git repo 內
  且未被 ignore，是的話警告——這個 repo 是公開的。`.gitignore` 也用
  `*cookie*.txt` / `*cookies*` 樣式擋，不要縮回固定檔名。
- **診斷失敗訊息不要推薦已被否定的做法**。`--authuser` 那類試過無效的方向
  一律不寫進提示，直接引導到 `--diagnose`。

## 開發指令

```bash
uv run download_meet.py --check          # 檢查環境，不下載
uv run download_meet.py --help
python3 -m py_compile download_meet.py   # 語法檢查
```

## 疑難排解

- **`ModuleNotFoundError: No module named 'yt_dlp'`**：使用者用的 python 沒裝 yt-dlp。
  腳本會捕捉這個並印出該機器適用的安裝指令，不要讓它變成 traceback。
- **HTTP 403 / 驗證失敗**：先跑 `--diagnose`。第 1 項（Drive 網頁版）是 ❌
  就是帳號沒權限，程式無解；第 4 項（get_video_info）的原因才是真線索。
- **cookie 到期**：Google 的登入 cookie（SID / SAPISID）多半以年計，
  不是幾小時。`cookie_expiry_summary()` 會印出實際到期日，不要用猜的。
- **改動檔名邏輯後**：記得驗證 `build_filename()` 對三種輸入格式的輸出
  （帶 GMT 括號、帶 CST 破折號、認不出格式）。
