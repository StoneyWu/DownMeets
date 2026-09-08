# DownMeets

下載 Google Drive 上設為「僅供檢視」、沒有下載按鈕的 Google Meet 會議錄影。

## 最快的用法

在你想放影片的資料夾底下執行一行，不用 clone、不用建虛擬環境、不用先裝任何 Python 套件：

```bash
uv run https://raw.githubusercontent.com/StoneyWu/DownMeets/customized/download_meet.py \
  "https://drive.google.com/file/d/檔案ID/view"
```

影片就存在**你執行指令時所在的那個目錄**。

沒有 `uv` 的話先裝（只需要這一次）：

```bash
brew install uv                              # macOS
curl -LsSf https://astral.sh/uv/install.sh | sh   # 其他系統
```

嫌網址太長，設個 alias：

```bash
alias downmeets='uv run https://raw.githubusercontent.com/StoneyWu/DownMeets/customized/download_meet.py'
# 之後就只要 downmeets "網址"
```

## 其他跑法

```bash
# clone 下來跑（一樣自動處理依賴）
uv run download_meet.py "網址"

# 一次多支
uv run download_meet.py "網址1" "網址2" "網址3"

# 批次：把網址一行一個寫進 urls.txt（# 開頭是註解），然後
uv run download_meet.py

# 先檢查這台機器的環境，不下載
uv run download_meet.py --check

# 不用 uv 的話
python3 -m venv .venv && .venv/bin/pip install yt-dlp
.venv/bin/python download_meet.py "網址"
```

## 選項

| 選項 | 說明 |
|------|------|
| `--browser 名稱[:profile]` | 從哪個瀏覽器讀登入 cookie，預設 `chrome`。可用：brave、chrome、chromium、edge、opera、vivaldi、whale、firefox、safari。多 profile 時可指定，例如 `--browser "chrome:Profile 1"` |
| `--cookies 檔案` | 改用匯出的 Netscape 格式 cookie 檔 |
| `--output 目錄` | 影片存放目錄，預設為當前目錄 |
| `--save-cookies 檔案` | 把這次讀到的瀏覽器 cookie 另存一份，之後用 `--cookies` 就不必再過鑰匙圈 |
| `--diagnose` | 逐層測試 Google 各端點，找出失敗卡在哪一層 |
| `--check` | 只檢查執行環境，不下載 |

## 驗證方式

預設直接讀你**瀏覽器裡現有的登入狀態**，不需要手動匯出 cookie。優先序：

1. `--browser 名稱` 明確指定
2. cookie 檔：`--cookies` 指定的檔案 > `$DOWNMEETS_COOKIES` > `./cookies.txt` > `./drive.google.com_cookies.txt`
3. 都沒有就用預設瀏覽器 Chrome

**Chrome 有多個 profile 時要指定。** yt-dlp 預設只讀 `Default`，你登入 Google 的若是別的 profile（工作帳號常見），會讀到一堆無關 cookie，最後表現成 HTTP 403。程式在讀不到 cookie 時會列出偵測到的 profile 清單：

```bash
--browser "chrome:Profile 1"
```

**macOS 讀 Chrome 系瀏覽器（Chrome / Brave / Edge 等）會跳出鑰匙圈授權視窗**，要按「允許」並輸入 **Mac 登入密碼**（開機解鎖用的那個，不是 Google 密碼）。若輸入了卻一直不被接受，多半是改過系統密碼但登入鑰匙圈還鎖在舊密碼上，用這行可以驗證：

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

macOS 每次讀 Chrome cookie 都會問（而且常常連問兩次——一次授權存取鑰匙圈項目、一次確認輸出明文）。授權一次就好的做法：

```bash
# 第一次：過鑰匙圈，順便把 cookie 存起來
uv run download_meet.py --save-cookies ~/.downmeets-cookies.txt "網址"

# 之後：完全不碰鑰匙圈
uv run download_meet.py --cookies ~/.downmeets-cookies.txt "網址"
```

Google 的登入 cookie（`SID`、`SAPISID` 等）通常是**長效的**，多半以年計而非小時。程式會直接印出實際到期日，不用猜：

```
有效期：最早到期的是 SAPISID，2027-10-13（還有 399 天）
```

真正會讓 cookie 失效的是登出 Google、改密碼，或 Google 主動終止 session。真的過期時，`--check --cookies 檔案` 和 `--diagnose` 都會標示 ❌，再跑一次 `--save-cookies` 更新即可。

不想跟鑰匙圈耗的話也可以用 `--browser firefox`，Firefox 的 cookie 沒加密，不需要任何授權。

自動讀不到的話（無頭機器、遠端 server、瀏覽器沒登入），改用匯出的 cookie 檔：

1. 瀏覽器安裝「Get cookies.txt LOCALLY」擴充套件
2. 登入 Google Drive
3. 匯出 `drive.google.com` 的 cookie，選 **Netscape 格式**（不是 JSON）
4. 存成 `cookies.txt` 放在執行目錄，或用 `--cookies 路徑` 指定

## 下載加速（選配）

裝了 `aria2c` 就會自動啟用，16 條連線平行下載：

```bash
brew install aria2              # macOS
sudo apt-get install -y aria2   # Debian / Ubuntu
```

沒裝也能跑，會改用 yt-dlp 內建下載器，只是慢一些。程式會自己偵測，不用設定。

平行下載數會跟著調整：有 aria2c 時 2 支同時下載（它自己已經開 16 連線，再多容易被 Google 限流），沒有時 4 支。

## 檔名與同名處理

Google Meet 的原始檔名帶著一長串時間戳，程式會清成 `YYYYMMDD - 會議標題.mp4`：

```
團隊會議 (2025-04-11 11:16 GMT+8)              →  20250411 - 團隊會議.mp4
專案討論 - 2025/04/07 16:52 CST - Recording    →  20250407 - 專案討論.mp4
```

認不出日期格式時只保留原標題，不會拿今天的日期充數。

碰到同名檔會**先問你**要怎麼處理：

```
⚠️  檔案已存在：20250411 - 團隊會議.mp4
    [r] 改名（存成「20250411 - 團隊會議 (2).mp4」）  [o] 覆蓋  [s] 跳過
    大寫 R / O / S 表示後續全部都這樣處理
```

在無法互動的環境（管線、CI）會自動跳過並印出訊息。

## 原理

Google Drive 就算關掉下載按鈕，還是得把影片串流餵給瀏覽器播放器——限制只做在 UI 層，網路層沒擋。所以帶著你的登入 cookie，用 yt-dlp 的 Google Drive extractor 找出串流端點直接抓，就繞過了「已停用下載選項」。

技術來源：Gabriel Diem 的文章 [How to download Google Meet meeting recordings set to "view only" mode](https://dev.to/gabrieldiem/how-to-download-google-meet-meeting-recordings-set-to-view-only-mode-4d2a)。

## 疑難排解

| 症狀 | 處理 |
|------|------|
| `ModuleNotFoundError: No module named 'yt_dlp'` | 你用的 python 沒裝 yt-dlp。改用 `uv run download_meet.py`，程式也會直接印出你這台機器該打的指令 |
| 驗證失敗、被導到登入頁 | 確認該瀏覽器登入的帳號看得到這支影片；或改用 `--browser firefox`；或改用匯出的 cookie 檔 |
| macOS 沒跳鑰匙圈視窗、讀不到 Chrome | 之前可能按過「拒絕」。用 `--browser firefox`，或改用 cookie 檔 |
| 下載很慢 | 裝 `aria2c` |
| 一直失敗 | 每支影片會自動重試 3 次。先跑 `--check` 確認環境 |

## 需求

- Python 3.10 以上（有 `uv` 的話它會自己準備）
- 唯一的 Python 依賴是 `yt-dlp`，由 PEP 723 內嵌宣告，`uv run` 自動安裝
- `aria2c` 選配

## 授權

本專案僅供學習用途。請遵守 Google 服務條款，只下載你有權存取的內容。
