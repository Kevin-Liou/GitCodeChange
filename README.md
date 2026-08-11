# Git Commit Extractor

把指定 commit(或工作區尚未 commit 的變更)所異動到的檔案,依「變更前 / 變更後」兩份完整檔案匯出到資料夾,方便直接丟給 Beyond Compare、WinMerge 之類的工具比對,或是打包交付、留存紀錄。

不是產生一份 diff 文字檔,而是**把整個檔案的前後版本各留一份**,連目錄結構一起還原。

![畫面](docs/screenshot.png)

---

## 環境需求

| 項目 | 需求 |
| --- | --- |
| 作業系統 | Windows(macOS / Linux 也可執行,開啟資料夾的行為會自動切換) |
| Python | 3.8 以上(開發環境為 3.11) |
| 套件 | `ttkbootstrap`、`GitPython` |
| 其他 | 系統需裝有 `git` 指令(產生 `changes.patch` 時會用到) |

安裝套件:

```powershell
pip install ttkbootstrap GitPython
```

## 執行

```powershell
python git_diff_export.py
```

---

## 介面說明

### ① Git 儲存庫

* 路徑欄位是**下拉式選單**,會記住用過的儲存庫,可直接挑選,也可以手動輸入或貼上。
* 按 `瀏覽…` 選資料夾;按 `✕` 把目前這筆路徑從歷史紀錄中移除。
* 路徑輸入後會即時驗證,顯示分支、HEAD、工作區是否有未提交變更。
* 驗證成功會自動載入 commit 清單與未提交檔案清單。

### ② 要匯出的內容(三種模式)

| 分頁 | 用途 |
| --- | --- |
| **Commit 清單** | 直接從清單挑 commit。可切換分支、調整載入筆數、用關鍵字搜尋(SHA / 作者 / 標題),按住 `Ctrl` / `Shift` 可複選多筆一次匯出;連按兩下可在執行紀錄看到完整 commit 訊息。 |
| **手動輸入 SHA** | 貼上一或多筆 SHA、分支名或 tag,以空白、逗號或換行分隔。 |
| **未提交的變更** | 匯出工作區目前尚未 commit 的內容(含已 `git add` 的部分),會先列出受影響的檔案清單。 |

### ③ 輸出資料夾

* 同樣是**下拉式選單**,記住用過的輸出路徑。
* `瀏覽…` 選資料夾、`開啟資料夾` 直接開檔案總管、`✕` 移除該筆歷史紀錄。
* 路徑不存在時,按下「開始匯出」會自動建立。

### ④ 選項

| 選項 | 說明 | 預設 |
| --- | --- | --- |
| 覆蓋已存在的輸出資料夾 | 關閉時遇到同名資料夾會略過。開啟時只會覆蓋「本工具產生的」資料夾(必須含 `ORG` / `MOD` / `commit_message.txt`),否則一樣略過,避免誤刪。 | 關 |
| 同時輸出 changes.patch | 以 `git diff` 產生 unified diff 檔。 | 開 |
| 資料夾名稱加上短 SHA | 資料夾後面補上 8 碼 SHA,避免同日期、同標題的 commit 互相衝突。 | 關 |
| 未提交模式包含未追蹤檔案 | 把 untracked 檔案也複製到 `MOD`。 | 開 |
| 完成後自動開啟輸出資料夾 | 匯出結束自動開啟檔案總管。 | 關 |

### ⑤ 選多筆 commit 時

選超過一筆 commit 時,決定要怎麼輸出:

| 模式 | 行為 |
| --- | --- |
| **分開匯出(每筆一個資料夾)** | 預設。選幾筆就產生幾個資料夾,每包各自是「該 commit 相對於它前一筆」的變更。 |
| **合併成一包(整段總變更)** | 把整段當成一次修改:`ORG` 是**最舊 commit 的前一版**,`MOD` 是**最新 commit 之後的版本**,中間改來改去的過程會被壓平。等同 `git diff <最舊>^ <最新>` 的結果。 |

合併模式的細節:

* 頭尾是依 **commit 的父子關係**判斷,不是看時間,所以 rebase / cherry-pick 過、或同一秒內建立的 commit 也不會弄反。
* 選取有跳號時(例如只選了 C1 和 C3,中間的 C2 沒選),會跳出確認視窗告訴你這段範圍實際包含幾筆、有幾筆沒被選到——**沒選到的那幾筆變更一樣會被合併進來**,因為範圍匯出本來就是頭尾兩個版本相減。
* 選到**不同分支**上的 commit 無法合併,會直接擋下來並提示改用分開匯出。
* 只選一筆時,自動退回一般的單筆匯出。
* 中間互相抵銷的修改(改了又改回來)不會出現在結果裡,這正是合併模式的用意。

### ⑥ 執行紀錄

依狀態上色:`ADDED` 綠、`DELETED` 紅、`MODIFIED` 藍、`RENAMED` 黃。匯出在背景執行緒進行,過程中介面不會卡住,可隨時按「取消」中止。

---

## 輸出結構

```
<輸出資料夾>/
└─ 2025-05-13_Fix_SMBIOS_type9_length_a1b2c3d4/
   ├─ ORG/                     變更前的檔案(原始版本,保留原目錄結構)
   │  └─ Silicon/Smbios/Type9.c
   ├─ MOD/                     變更後的檔案(修改版本)
   │  └─ Silicon/Smbios/Type9.c
   ├─ commit_message.txt       commit 資訊 + 變更檔案清單
   └─ changes.patch            unified diff(可關閉)
```

資料夾命名規則:

| 模式 | 命名 |
| --- | --- |
| 單筆 commit | `YYYY-MM-DD_<commit 標題>`,勾選短 SHA 後再加 `_<短 SHA>` |
| 合併多筆 | `YYYY-MM-DD_<最新 commit 標題>_merged<筆數>`,勾選短 SHA 後再加 `_<最舊>-<最新>` |
| 未提交變更 | `YYYY-MM-DD_HHMM_uncommitted` |

合併模式的 `commit_message.txt` 會多列出範圍與被合併的每一筆 commit:

```
Range:   0ad78f1c..4d48b5bf
Commits: 3

Merged commits (oldest → newest):
  14ea2d43  2025-05-11 18:51  Kevin  C1 change a
  ca3e22c5  2025-05-12 09:20  Kevin  C2 add b
  4d48b5bf  2025-05-13 14:02  Kevin  C3 change a again
```

`commit_message.txt` 範例:

```
Commit:  b82cdb189b4425d672674b3a7cd10ba57cb0d178
Author:  Kevin <kevin@example.com>
Date:    2025-05-13T09:55:50
Parent:  100f01450bb595a3a787b77f6ae34d2316c34742

Message:
Fix SMBIOS type9 length

Summary: ADDED 1, MODIFIED 7  (total 8)

Changed files:
  [MODIFIED] Silicon/Smbios/Type9.c
  [ADDED]    Silicon/Smbios/Type9.h
```

各狀態對應到的輸出:

| 狀態 | ORG | MOD |
| --- | --- | --- |
| MODIFIED | ✔ | ✔ |
| ADDED / UNTRACKED | — | ✔ |
| DELETED | ✔ | — |
| RENAMED | ✔(舊路徑) | ✔(新路徑) |

---

## 快捷鍵

| 按鍵 | 功能 |
| --- | --- |
| `Ctrl` + `Enter` | 開始匯出 |
| `F5` | 重新載入 commit 清單 |
| `Ctrl` / `Shift` + 點選 | 在清單中複選 commit |
| 連按兩下 | 顯示該 commit 的完整訊息 |

---

## 設定檔

所有設定存在 `%USERPROFILE%\.git_export_tool_config.json`,關閉視窗時自動寫入:

* `repo_history` / `out_history`:路徑下拉選單的歷史紀錄(最多 12 筆,最近用過的排最前面)
* `git` / `out` / `sha` / `branch` / `limit`:上次使用的欄位內容
* `theme`:外觀主題
* `size`:視窗大小
* `options`:各項選項的勾選狀態,含 `merge_mode`(`separate` / `merged`)

想全部重來,直接刪掉這個檔案即可。

---

## 注意事項與已知限制

* **覆蓋選項會刪除整個目標資料夾**。雖然有「必須看起來像本工具輸出」的防呆,仍建議輸出到專用資料夾,不要指到桌面或專案根目錄。
* 不會遞迴進 submodule 或 `.gitman` 子專案,只處理所選儲存庫本身。
* `changes.patch` 在未提交模式下**不包含 untracked 檔案**(`git diff` 的行為)。
* 二進位檔案照樣會複製完整檔案,但 patch 內只會顯示 `Binary files differ`。
* 路徑超過 240 字元時會自動加上 `\\?\` 前綴繞過 Windows MAX_PATH 限制。
* 合併模式匯出的是**頭尾兩個版本的差異**,不是把每筆 commit 的變更逐一疊加。範圍內沒被選到的 commit,其變更同樣會包含在內。
* 儲存庫很大時,建議把「筆數」調小一點再載入 commit 清單。
* 選儲存庫時要選到含 `.git` 的那一層,不會往上層目錄自動尋找。

---

## 專案檔案

| 檔案 | 說明 |
| --- | --- |
| `git_diff_export.py` | 全部程式碼(核心 + GUI),單檔即可執行 |
| `README.md` | 本說明文件 |
| `.gitignore` | 忽略清單 |

程式內部已把核心與介面分開,`extract_commit()` 與 `extract_working_tree()` 不依賴 tkinter,可以直接被其他腳本匯入使用:

```python
from git import Repo
from git_diff_export import Reporter, extract_commit, extract_commit_range

repo = Repo(r"D:\Code\MyProject")

# 單筆
extract_commit(repo, "HEAD", r"D:\out", Reporter(), name_with_sha=True)

# 多筆合併成一包
extract_commit_range(repo, ["HEAD", "HEAD~1", "HEAD~2"], r"D:\out", Reporter())
```

> 舊版以 PyQt5 撰寫的 `Git_code_change.py` / `Git_lib.py` / `UI/` 已移除,需要時可從 git 歷史(commit `b82cdb1` 以前)取回。
