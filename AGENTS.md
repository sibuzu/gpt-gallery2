<!-- worknerd:project-reporting:v1 -->
## Master Agent 與工作宅通報

- **Master Agent／本機 Master**：本專案實際所在機器（worknerd、nerd-r5090 或 nerd-rtx）的常駐工作宅 node，負責本機任務、子 agent、Scheduler 與持久回報；本次互動 Codex 是專案執行者。專案原有的 root／Agent1 等名稱保留原職責。
- **工作宅**：由 worknerd 提供的中央管理系統，網址 https://nerd.sibuzu.com。通報路徑為「專案 Codex → 本機 Master 的持久 outbox → worknerd 中央任務／訊息紀錄」；在 worknerd 上，本機 Master 同時屬於中央節點。
- 在本專案另開 Codex 對話，進行更新、編修、新增功能、資料／設定／規則異動時，也必須執行以下通報。這是代理必須遵守的工作規則；常駐 Master 不會自動讀取其他 Codex 對話或監看所有檔案變更。
- 使用者說「向 Master Agent 通報……」或「向工作宅通報……」時，由目前 Codex 實際送出通報，附本機、專案、task ID（如有）、內容及證據。工作進度與單純告知均用 report／progress，由本機 Master 轉送中央。通報指示本身不代表另派一份相同工作。

### 獨立 Codex 的操作

1. 先確認 cwd、Git 根目錄／worktree 的來源、git status 與本機設定；保留其他工作階段的未提交變更。先讀下列 `status`，以 `machine` 確認實際機器，以 `projects` 中符合**本 Git 專案根目錄**的有效登記取得 PROJECT_ID。巢狀獨立 Git repo 使用自己的登記；同 repo 的子目錄／worktree 使用同一專案。不要沿用別台的 project ID；多台共用的 repo 也依本機查證。
2. 修改、派子 agent 或操作服務前，以 `report --status running --stage received` 登記，使用本次工作唯一的 idempotency key。讀回 `status.deliveries` 中相同 dedupe 的 `task_id`，確認中央已收件。有本次工作的 task ID 時直接續用，不另建重複任務。
3. 重要進展與測試結果使用同一 TASK_ID 的 `progress` 追加。完成回報列修改、實際驗證、commit SHA（未提交則註明）、失敗／未測項及剩餘變更；依實況選 done／review／needs_input／failed／interrupted。已自行執行的工作不再 submit 給常駐 Master 重跑。
4. 本機 node 的 machine 身分不能用 message 給自己；專案向本機 Master 通報使用上述 report／progress，不使用 self-message。僅收到 `queued_locally` 代表本機已排隊；應再核對送達回執。中央離線或 CLI 不可用時，保留待送內容及錯誤並向使用者說明，恢復後沿用原 key／task 補送；不能宣稱中央已收到。送達、Master 模型答覆與使用者已讀分別判定。

三台目前的 CLI 所在位置如下；若本機安裝不同，先讀該機 LOCAL.md 查證，不猜測或讀取憑證：

```bash
wn() { docker compose --project-directory /home/jack/codex/projects/nerd-infra/worknerd exec -T node python -m worknerd "$@"; }
wn status
wn report --project PROJECT_ID --title '本次工作名稱' \
  --instructions '本次需求與範圍' --body '已收到需求，準備修改；專案與驗收方式……' \
  --status running --stage received --idempotency-key '本次工作唯一識別'
wn status  # 核對 deliveries 的 dedupe 與 task_id
wn progress --task TASK_ID --stage implementation --body '實際修改及目前進度……' --status running
wn progress --task TASK_ID --stage completed --body '修改、驗證、commit或未提交、限制……' --status done
# 單純通報且尚無相關 task 時，建立一筆已完成的通報紀錄：
wn report --project PROJECT_ID --title '專案狀態通報' \
  --body '專案、實際變動及證據……' --status done --stage notification \
  --idempotency-key '本次通報唯一識別'
# 已有相關 task 時改用 progress 追加通報，status 沿用該工作的實際狀態。
```

通報沿用本機 node 的受控 CLI；不將服務 token、登入或私鑰放入專案文件、Git、提示詞或回報。commit、push、部署與其他外部操作仍依使用者當次授權及本專案原有規則；本段不恢復歷史任務或擴大授權。完整共用規則見本機 `/home/jack/codex/projects/nerd-infra/worknerd/PROJECT-REPORTING.md`，本段已包含獨立開啟專案所需的定義與命令。
<!-- /worknerd:project-reporting:v1 -->

# Gallery 2 維護

- 更新前先讀取 [UPDATE_RULES.md](UPDATE_RULES.md)，其中保存使用者已確認的匯入、命名、鏡像、分類、分析及建置要求。
- 使用者在對話中的最新指示優先；持續適用的新要求要同步記錄。
- 此目錄是獨立 Git repository。主 repository 的提交不會包含此目錄的變更。
- 建置需 Python 3.11 以上及 Pillow。執行 `build_gallery.py` 後，檢查圖庫快照、分類數量、圖片與同名 prompt 配對，以及修改過的 JavaScript 語法。
