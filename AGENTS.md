# Gallery 2 維護

- 更新前先讀取 [UPDATE_RULES.md](UPDATE_RULES.md)，其中保存使用者已確認的匯入、命名、鏡像、分類、分析及建置要求。
- 使用者在對話中的最新指示優先；持續適用的新要求要同步記錄。
- 此目錄是獨立 Git repository。主 repository 的提交不會包含此目錄的變更。
- 建置需 Python 3.11 以上及 Pillow。執行 `build_gallery.py` 後，檢查圖庫快照、分類數量、圖片與同名 prompt 配對，以及修改過的 JavaScript 語法。
