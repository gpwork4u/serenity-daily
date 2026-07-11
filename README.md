# Serenity 卡點投資 · 每日研究記錄

用 Serenity（@aleabitoreddit）「物理卡點」框架，對美股／歐股與台股 AI 光通訊供應鏈候選股做的**每日研究觀察清單**。由 claude.ai 雲端排程每天台北時間 08:00 自動更新。

- **最新一期**：[`index.html`](./) → https://gpwork4u.github.io/serenity-daily/
- **歷史存檔**：[`archive.html`](./archive.html) ｜ 每日快照存於 [`history/`](./history/)

## ⚠️ 免責

這是套用卡點框架的**研究輔助清單，不是投資建議、不是買賣指令、也不是個人化配置建議**。頁面中的「示意權重」僅依信念分級機械換算，屬教學示意，不代表應買進或該持有的比例。許多數字為自述／媒體轉述或落後一季的資料；每一檔結論都必須用最新財報、法說、重大訊息與即時行情自行覆核。清單多為波動極大、流動性薄的中小型股——追高會使你成為擁擠交易的一部分。

## 運作方式

每日雲端 agent：讀取 `serenity-chokepoint-investing` 框架 → 對 12 檔即時網路研究 → 依固定 HTML 版型產出報告 → 覆寫 `index.html`、新增 `history/YYYY-MM-DD.html`、重建 `archive.html` → commit + push（GitHub Pages 自動發布）。
