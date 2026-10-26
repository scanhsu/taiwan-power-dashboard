# 臺灣電力儀表板

即時供電燈號、今日用電曲線、能源結構、區域供需、縣市用電地圖，以及可以看風機轉動、煙囪冒煙的「遊戲島嶼」模式。

資料來源是台電「今日電力資訊」與政府資料開放平臺，由 GitHub Actions 每 10 分鐘自動抓取，再發布到 GitHub Pages。完全免費，不需要自己的伺服器。

## 檔案說明

| 檔案 | 用途 |
| --- | --- |
| `index.html` | 網頁本體（儀表板＋遊戲島嶼） |
| `scripts/update_data.py` | 抓台電資料、整理成 JSON 的程式 |
| `.github/workflows/update.yml` | 排程設定：每 10 分鐘執行一次抓資料並發布網站 |
| `data/` | 自動產生的資料（不用手動放東西） |

## 第一次設定（約 15 分鐘）

### 步驟 1：建立儲存庫

1. 登入 [GitHub](https://github.com)（沒有帳號就先免費註冊）。
2. 右上角「＋」→「New repository」。
3. Repository name 填 `taiwan-power-dashboard`。
4. 選 **Public**（免費帳號的 GitHub Pages 需要公開）。
5. 其他選項都不要勾，按「Create repository」。

### 步驟 2：上傳檔案

1. 在新儲存庫的頁面點「uploading an existing file」。
2. 把解壓縮後的 `index.html`、`README.md`、`scripts` 資料夾、`data` 資料夾拖進去。
3. 下方按「Commit changes」。

> `.github` 資料夾在 Mac 和 Windows 預設是隱藏的，拖曳時常會漏掉，所以排程檔改在步驟 4 用網頁建立。

### 步驟 3：開啟 GitHub Pages

1. 儲存庫上方點「Settings」。
2. 左邊選單點「Pages」。
3. 「Build and deployment」下的 **Source** 選「**GitHub Actions**」。

### 步驟 4：建立排程檔

1. 回到儲存庫首頁（點上方「Code」）。
2. 點「Add file」→「Create new file」。
3. 檔名欄位輸入 `.github/workflows/update.yml`（打到 `/` 時會自動變成資料夾，這是正常的）。
4. 打開壓縮檔裡的 `.github/workflows/update.yml`，全選複製，貼到網頁的大框框裡。
5. 按右上「Commit changes...」→ 再按一次「Commit changes」。

### 步驟 5：確認第一次執行成功

1. 點上方「Actions」。
2. 會看到「更新台電資料並發布網站」正在跑（黃色圓圈）。等 1～2 分鐘變成綠色勾勾。
3. 點進去，最後一個步驟「發布網站」下面會有網址，格式是：
   `https://你的帳號.github.io/taiwan-power-dashboard/`
4. 打開網址，右上角顯示「台電即時資料」就成功了。把網址傳給朋友即可。

## 之後會自動做的事

- 每 10 分鐘抓一次台電資料並更新網站（GitHub 的排程常延遲 5～15 分鐘，屬正常）。
- 每天晚上把今天的用電曲線存起來，隔天顯示成「昨日用電」。
- 每天記錄前一天的尖峰備轉容量率，第一次執行時也會從開放資料補上過去的紀錄。
- 每週檢查一次縣市用電統計；成功抓到後，地圖上的「示意值」字樣會消失。

## 常見問題

**Actions 出現紅色叉叉，訊息有 `Permission denied` 或 `403`**
Settings → Actions → General → 最下面「Workflow permissions」選「Read and write permissions」→ Save，再到 Actions 頁面按「Re-run jobs」。

**「發布網站」步驟失敗，說 Pages 沒有啟用**
回到步驟 3，確認 Source 是「GitHub Actions」，然後重新執行。

**網頁右上角顯示「資料已 XX 分鐘未更新」**
通常是 GitHub 排程延遲或台電網站維護，等一下就會恢復。可以到 Actions 頁面點左邊的工作流程，再按「Run workflow」手動更新。

**想在自己電腦先試抓資料**
安裝 Python 3 後，在這個資料夾打開終端機執行：

```
python scripts/update_data.py
```

完成後 `data/latest.json` 就是最新資料。

## 資料說明

- 即時資料：台電 `loadpara.json`、`genary.json`、`loadfueltype.csv`、`loadareas.csv`、`genloadareaperc.csv`。
- 遊戲島嶼的各電廠出力：依台電逐機組名稱加總；太陽能約八成以上沒有單獨列出，依地區比例分配，屬推估。回放過去時間時，以現在機組出力按當時全台該能源發電比例換算。
- 縣市用電：住宅、服務業及機關為每月實際售電量；含工業的總用電依年度用電比例推估。
- 本網站為個人作品，與台灣電力公司無關。
