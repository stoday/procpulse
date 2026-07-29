# ProcPulse PRD

## 1. 專案概述

ProcPulse 是一個高可靠度、跨平台的 Python 工具庫與 CLI，供開發者及 Agent 安全地執行與管理任意外部命令與程序，例如 `python`、`git`、`ls`、`npm`、shell script、compiled binary 與其他子行程。

第一版聚焦於三項能力：

- 即時輸出：同步、逐行取得外部程序的 stdout 與 stderr。
- 集中管理：透過 `ProcessManager` 追蹤、查詢與控制外部程序。
- Process tree 清理：任務被取消、逾時或手動停止時，清理目標程序及套件可控制範圍內的衍生程序。

套件支援 Linux、macOS 與 Windows。文件中的「清理 process tree」指受 process group 或 Windows Job Object 控制的程序；若子程序主動脫離控制範圍、權限不足或被系統轉交給其他服務，套件必須回報清理失敗，不宣稱絕對能終止所有外部程序。

## 2. 第一版設計決策

- stdout 與 stderr 合併為單一事件流，每筆事件保留輸出來源 `channel`。
- 第一版提供同步 API；內部實作應避免把 API 設計成無法日後加入 async 介面的形式。
- `stop()` 先嘗試 graceful termination，等待 grace period 後，仍未結束才 force kill 整個受控 process tree。
- 事件流結束前必須排空 stdout 與 stderr 的剩餘緩衝資料。
- `outcome` 保存 stdout 與 stderr 的完整內容，並受可配置的輸出上限約束。

## 3. 核心架構與 API

### 3.1 ProcessManager

`ProcessManager` 負責初始化、追蹤、查詢與批次控制所有由它啟動的外部程序。

```python
process_manager.build() -> ProcessManager
manager.run_external_process(command, args=None, **options) -> ProcessObject
manager.list(filter=None) -> list[ProcessObject]
manager.stop(process_id, grace_period=2.0) -> StopResult
manager.close(wait=True) -> None
```

啟動外部程序時，第一版預設使用 argument list 與 `shell=False`。若支援 shell execution，必須由呼叫端明確啟用並在 API 文件中說明命令注入風險。

可配置的啟動選項包括：

- `cwd`：工作目錄。
- `env`：環境變數覆寫值。
- `encoding` 與 `errors`：輸出解碼策略。
- `output_limit`：stdout/stderr 各自的保存上限。
- `timeout`：程序最長執行時間。

Manager 關閉後不得再啟動新程序。`close(wait=True)` 應等待受控程序完成並排空輸出；`close(wait=False)` 僅停止接受新工作並立即返回，背景清理仍會繼續。關閉 Manager 不會自動停止仍在執行的程序；需要停止程序時，呼叫端應明確使用 `stop()`。

### 3.1.1 Persistent CLI

CLI 必須支援跨命令呼叫管理長時間程序：

```bash
procpulse start -- COMMAND [ARGS...]
procpulse list
procpulse status PROCESS_ID
procpulse output PROCESS_ID
procpulse stop PROCESS_ID
procpulse clean
```

`start` 應立即回傳 process ID，由 background monitor 持有程序生命週期。record 與 stdout/stderr 預設保存於目標工作目錄下的 `.procpulse/`；可用 `PROCPULSE_HOME` 覆寫。`clean` 只清理已完成或失敗的 record 與輸出，不得刪除仍在執行的程序資料。

### 3.2 ProcessObject

`ProcessObject` 封裝單一外部程序的識別資料、動態狀態、事件流與最終結果。

```python
process_obj.id       # Manager 內唯一的穩定識別碼
process_obj.status   # 動態狀態物件
process_obj.stream   # 同步、單次消費的事件 iterator
process_obj.outcome  # 程序結束後可取得的結果
```

`id` 不等同於作業系統 PID。`pid` 應作為 status 的欄位保存，因為程序結束後 PID 可能被系統重用。

狀態至少包括：

- `starting`
- `running`
- `stopping`
- `finished`
- `failed`

status 至少包含：

- `state`
- `is_alive`
- `pid`
- `uptime`
- `return_code`
- `cmd`：實際執行的 immutable command tuple，包含 executable 與所有 arguments。
- `work_dir`：實際使用的絕對工作目錄。

### 3.3 StreamEvent

`stream` 是同步 iterator，事件採用 typed event object，不使用 tuple 或未定義欄位的 dictionary。

```python
for event in process_obj.stream:
    print(event.channel)    # "stdout" 或 "stderr"
    print(event.text)
    print(event.timestamp)
```

每筆 `StreamEvent` 至少包含：

- `channel: Literal["stdout", "stderr"]`
- `text: str`
- `timestamp: datetime`

事件應在資料可讀取時儘快產生。呼叫端未讀取 stream 時，背景讀取機制仍不得讓子程序因 pipe buffer 滿而 deadlock；輸出應持續進入內部 buffer，並依 `output_limit` 進行保存或截斷。

程序結束後，stream 必須繼續產出所有已進入 pipe 但尚未交付的事件，全部輸出排空後才結束 iterator。第一版 stream 為單次消費；不承諾多個 consumer 同時訂閱同一事件流。

### 3.4 Outcome

程序仍在執行時，`outcome` 不可視為完成結果；呼叫端應先消費完 stream 或等待程序結束。

程序結束後，`outcome` 至少包含：

- `stdout: str`
- `stderr: str`
- `exit_code: int | None`
- `duration`
- `termination_reason`
- `output_truncated: bool`

`termination_reason` 的允許值為：

- `completed`：程序正常結束。
- `failed`：程序啟動失敗或以非預期錯誤結束。
- `cancelled`：由呼叫端取消。
- `timeout`：超過設定的執行時間。
- `killed`：graceful termination 無效後被強制終止。

stdout 與 stderr 必須分開保存。每個 channel 的保存上限可配置；超過上限時，套件可停止保存超出的部分，但仍必須繼續讀取 pipe，以避免阻塞，並將 `output_truncated` 設為 `True`。

## 4. 跨平台執行與 Process tree 清理

### 4.1 Linux / macOS

啟動程序時建立獨立 process group，例如使用 `os.setsid`。停止時先對 process group 發送 graceful termination signal；逾時後再對整個 process group 發送 force kill signal，最後等待並回收主程序。

### 4.2 Windows

優先使用 Windows Job Object 管理主程序及其衍生程序。停止時先嘗試 graceful termination，逾時後終止 Job Object 內仍存活的程序，並等待主程序回收。

若平台 API、權限或程序行為導致部分程序無法清理，`stop()` 必須回報可辨識的錯誤，且 outcome/status 應反映清理未完成。

## 5. Stop 行為

```python
manager.stop(process_id, grace_period=2.0)
```

停止流程如下：

1. 驗證 `process_id` 存在且仍受 Manager 追蹤。
2. 將狀態設為 `stopping`。
3. 對受控 process group 或 Job Object 發送 graceful termination。
4. 等待 `grace_period`。
5. 若仍有程序存活，強制終止受控 process tree。
6. 等待主程序結束、排空輸出並回收資源。
7. 產生完整 outcome 與停止結果。

對已完成程序重複呼叫 `stop()` 應是冪等的，或回傳明確的 already-finished 結果；對不存在的 ID 應拋出專用的 `ProcessNotFoundError`。停止失敗與 process tree 未完整清理時，應拋出專用錯誤或在 `StopResult` 中明確標示。

## 6. 錯誤處理

至少需要定義以下錯誤類型或等價的穩定錯誤分類：

- executable 不存在。
- 權限不足。
- Manager 已關閉。
- process ID 不存在。
- 停止逾時或 process tree 清理失敗。
- 輸出解碼失敗。

錯誤不得讓背景讀取執行緒靜默遺失；相關錯誤應可透過 process outcome、status 或專用例外被呼叫端觀察。

## 7. 驗收條件與測試

- stdout/stderr 混合輸出時，事件保留正確 `channel`，且讀取不會 deadlock。
- 程序結束後，stdout/stderr 尾端緩衝資料不遺失。
- graceful termination 成功時，不執行 force kill。
- graceful termination 失敗時，能清理受控範圍內的多層衍生程序。
- `grace_period` 可覆寫，預設為 2 秒。
- 大量輸出超過上限時，pipe 仍持續被讀取，且 outcome 明確標記截斷。
- 不存在的 executable、權限錯誤與不存在的 process ID 會產生穩定錯誤。
- 重複呼叫 `stop()` 不會造成未處理的非預期例外。
- Manager 關閉後無法啟動新程序。
- Linux、macOS 與 Windows 均有對應的 process-tree 測試；平台不支援時必須明確標記測試狀態。
- 正常完成、非零 exit code、cancel、timeout、graceful stop 與 force kill 都能產生正確的 `termination_reason`。

## 8. 使用範例

```python
from my_toolkit import process_manager

manager = process_manager.build()
process_obj = manager.run_external_process(
    "python",
    args=["long_running_script.py", "--parallel"],
    timeout=300,
)

print(f"已啟動程序，ID 為: {process_obj.id}")

for event in process_obj.stream:
    print(f"[{event.channel}] {event.text.rstrip()}")

manager.stop(process_obj.id, grace_period=2.0)
print(process_obj.outcome)
manager.close()
```
