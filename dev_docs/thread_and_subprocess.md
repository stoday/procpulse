# ProcPulse 的 thread 與 subprocess 使用方式

## 結論

ProcPulse 採用「`subprocess` 執行外部程式、`thread` 負責非同步管理」的架構。

外部命令本身不是在 Python thread 中執行，而是由作業系統建立獨立的 child process。ProcPulse 再使用數個 daemon thread 讀取輸出、監控結束狀態，以及在需要時處理 timeout。這讓對外 API 可以維持同步、簡單的介面，同時避免 stdout/stderr pipe 堵塞或長時間等待阻塞主呼叫端。

```text
呼叫端 thread
    │
    └── ProcessObject
          ├── subprocess.Popen          外部命令
          ├── stdout reader thread      讀 stdout
          ├── stderr reader thread      讀 stderr
          ├── watcher thread            等待結束、建立 outcome
          └── timeout timer thread      觸發 stop（設定 timeout 時才有）
```

## Python API 的啟動流程

呼叫 `ProcessManager.run_external_process()` 時，ProcPulse 會為每個命令建立一個 `ProcessObject`，並由排程模式決定何時啟動它：

1. 將命令解析為 argument list。
2. 將裸的 `python`/`python3` 解析為目前使用的 Python interpreter。
3. 以 `subprocess.Popen` 建立外部程序。
4. 將 stdin 設為 `DEVNULL`，stdout 和 stderr 設為 `PIPE`。
5. 使用 `shell=False`，因此命令不是交給 shell 解析。
6. 建立並啟動 stdout reader、stderr reader 與 watcher thread。
7. 立即回傳每個命令對應的 `ProcessObject` 集合，呼叫端不必等外部程序完成才取得控制權。

目前 `Popen` 的重要設定如下：

```python
subprocess.Popen(
    args=command_line,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    shell=False,
)
```

因此，真正執行 `python`、`git`、`npm`、shell script 或 compiled binary 的，是獨立的 subprocess。

## Thread 的用途

### 1. stdout 與 stderr reader thread

ProcPulse 為 stdout 和 stderr 各建立一個 thread。每個 thread 逐行讀取對應的 pipe，並做兩件事：

- 將文字保存到該 channel 的內部 buffer。
- 將文字包裝成 `StreamEvent`，放入共用的 queue。

兩個 channel 分開讀取很重要：如果只讀其中一個 pipe，另一個 pipe 的作業系統 buffer 可能填滿，造成 child process 永遠卡住。持續讀取兩者可以避免這類 pipe deadlock。

`StreamEvent` 包含：

- `channel`：`stdout` 或 `stderr`
- `text`：該行文字
- `timestamp`：UTC timestamp

呼叫端透過 `process.stream` 取得這些事件。這個 iterator 是同步、單次消費的介面；背後的 reader thread 仍會持續工作，即使呼叫端暫時沒有消費事件。

### 2. watcher thread

watcher thread 會等待 `Popen` 對象結束。child process 結束後，它會：

1. 記錄完成時間。
2. 等待 stdout/stderr reader thread 排空 pipe 中的尾端資料。
3. 取消 timeout timer。
4. 組合 stdout、stderr、exit code、duration 與 termination reason。
5. 建立 `ProcessOutcome`。
6. 設定完成事件，並在 stream queue 放入結束標記。
7. 關閉平台 backend。

這個順序確保「程序已結束」不代表輸出已經全部交付；`process.stream` 會等到輸出排空後才結束。

### 3. timeout timer

如果設定 `timeout`，watcher 會建立 `threading.Timer`。時間到時，timer thread 呼叫 `process.stop(reason=TIMEOUT)`。如果程序已經完成，timer 不會重複停止它。

### 4. `display()` 的 reader thread

`manager.display()` 在外部程序既有的 reader thread 之外，還會為每個 active `ProcessObject` 建立一個 display reader thread。這些 thread 消費 `process.stream`，再將事件放入 display 專用 queue。

display 的主 coordinator loop 負責實際寫出文字與狀態，因此多個程序的輸出不會由多個 thread 同時寫入 terminal 而互相交錯。

## 停止、timeout 與 process tree

`stop()` 的等待與終止操作是針對 subprocess，不是針對 Python thread：

1. 將狀態設為 `stopping`。
2. 透過平台 backend 對 child process 或其受控範圍發送 graceful termination。
3. 等待 `grace_period`。
4. 若仍未結束，force kill process tree。
5. 等待 subprocess 結束，再由 watcher thread 完成輸出排空與 outcome 建立。

平台 backend 負責 process tree 的差異：

- Linux/macOS：root process 使用獨立 process group；停止時使用 process group signal。nested ProcPulse 則使用 `psutil` 找 descendants，避免誤殺外層 process group。
- Windows：優先使用 Job Object；建立或 attach 失敗時，fallback 到 `taskkill /PID <pid> /T /F`。

Python thread 本身不代表外部命令的 process tree，也不能取代 subprocess 的終止。停止 thread 不會停止 child process，因此 ProcPulse 的控制目標是 subprocess 與其受控 descendants。

## Persistent CLI 的差異

Persistent CLI 使用另一層 subprocess 來讓程序跨多次 CLI 呼叫持續存在：

```text
procpulse start
    └── monitor subprocess
          └── target subprocess（真正的使用者命令）
```

`procpulse start` 會啟動一個 background monitor subprocess 後立即回傳 process ID。monitor subprocess 再啟動真正的 target subprocess，並：

- 將 stdout/stderr 直接寫入 `.procpulse` output files。
- 定期讀取 record，檢查是否收到 stop request。
- 執行 graceful termination 或 force kill。
- 更新 state、PID、exit code、termination reason 與完成時間。

這個 persistent CLI monitor 主要使用 polling loop 和 `Popen.wait()`，不是用 Python thread 來代替 target subprocess。CLI 的 `display` 或 `output` 命令是在之後的 CLI 呼叫中讀取已保存的輸出檔案。

## 執行模型比較

| 元件 | 執行形式 | 主要責任 |
| --- | --- | --- |
| 使用者命令 | OS subprocess | 實際執行外部程式 |
| stdout reader | daemon thread | 讀取 stdout，避免 pipe 堵塞 |
| stderr reader | daemon thread | 讀取 stderr，避免 pipe 堵塞 |
| watcher | daemon thread | 等待 subprocess、處理完成與建立 outcome |
| timeout timer | daemon timer thread | 到期時觸發停止 |
| `display()` reader | daemon thread | 消費 stream 並轉交 display coordinator |
| persistent CLI monitor | OS subprocess | 跨 CLI 呼叫持有 target subprocess 的生命週期 |

## 對外 API 的影響

- `run_external_process()` 啟動後會快速回傳每個命令對應的 `ProcessObject` 集合，不會同步等待命令完成。
- `mode="sequence"` 會由排程 thread 依序啟動命令；前一個程序失敗時，後續 `ProcessObject` 會進入 `skipped`。
- `mode="parallel"` 會啟動所有通過預檢的命令；每個程序的生命週期與結果彼此獨立。
- `process.status` 可在執行期間查詢 subprocess 的 PID、state 和 return code。
- `process.stream` 是同步 iterator，但事件由背景 reader thread 生產。
- `process.wait()` 等待 watcher thread 完成，並回傳 `ProcessOutcome`。
- `process.outcome` 只有在 subprocess 結束且 stdout/stderr 排空後才會建立。
- `manager.display()` 會阻塞到指定的程序及其輸出全部完成。
- `manager.close(wait=True)` 會等待受控程序完成；它不會自動停止仍在執行的 subprocess。

## 常見誤解

### 「有 thread，所以命令是在 thread 裡執行」

不是。thread 只負責與 subprocess 溝通和監控；外部命令是由 `subprocess.Popen` 建立的獨立 OS process。

### 「停止 watcher thread 就能停止命令」

不是。必須透過 backend 對 subprocess 或受控 process tree 發送 termination/kill。watcher thread 只是觀察並整理結果。

### 「subprocess 結束就能立刻結束 stream」

不一定。stdout/stderr reader 可能還有 pipe 尾端資料尚未交付，因此 watcher 會先 join reader threads，再標記 stream 完成。

### 「多個 thread 可以讓同一個 stream 被重播」

不是。`process.stream` 是 single-consumer iterator。若程序已完成，應從 `process.outcome.stdout` 和 `process.outcome.stderr` 取得已保存結果。

## 相關實作位置

- `ProcessObject`：建立 `Popen`、reader threads、watcher 與 outcome。
- `ProcessManager`：建立與追蹤 `ProcessObject`。
- `display`：並行消費多個 stream，集中輸出事件與狀態。
- `ProcessBackend`：抽象化平台差異。
- `UnixProcessBackend`：管理 Unix process group 與 nested descendants。
- `WindowsProcessBackend`：管理 Job Object 與 `taskkill` fallback。
- `cli`：實作 persistent monitor subprocess 與檔案化輸出。
