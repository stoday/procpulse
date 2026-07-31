# 批次外部程序執行與命令安全檢查：已實作功能規格

## 文件狀態

- 狀態：已實作
- 首次完成 commit：`650123d`（`feat: add safe batch process execution`）
- 最後核對日期：2026-07-31
- 實作範圍：Python API；Persistent CLI 尚未提供批次排程

## 功能摘要

ProcPulse 的 `ProcessManager.run_external_process()` 接受一個完整命令字串，或由多個完整命令字串組成的 sequence。每個命令都對應一個獨立的 `ProcessObject`，並依 `mode` 選擇順序或平行排程。

本功能已移除舊版 `args` 參數。命令字串會先經過整批安全預檢，再解析成 argv，最後固定以 `shell=False` 建立 subprocess。ProcPulse 不接受 pipe、命令串接、重導向等 shell 控制語法；使用者應將工作拆成多個命令，交由 `sequence` 或 `parallel` 管理。

## 公開 API

```python
processes = manager.run_external_process(
    command,
    mode="sequence",
    cwd=None,
    env=None,
    encoding="utf-8",
    errors="replace",
    output_limit=10 * 1024 * 1024,
    timeout=None,
)
```

### 輸入

- `command` 接受 `str` 或 `Sequence[str]`。
- 單一字串代表一個完整命令。
- sequence 中的每個字串各代表一個完整命令，不會被解讀成單一 executable 的 arguments。
- 空 sequence、含有非字串元素的 sequence，以及解析後為空的命令會在 subprocess 啟動前被拒絕。
- 裸的 `python`、`python3`、`python.exe` 與 `python3.exe` 會解析為目前執行 ProcPulse 的 `sys.executable`；明確 interpreter 路徑保持不變。

### 回傳值

回傳 `list[ProcessObject]`，順序與輸入命令相同。即使只傳入一個命令字串，仍回傳只含一個元素的 list。

每個 `ProcessObject` 分別提供：

- ProcPulse process ID 與 OS PID
- `status`
- single-consumer `stream`
- `wait()` 與 `stop()`
- stdout/stderr 分離的 `outcome`

## 啟動選項

- `mode`：`"sequence"` 或 `"parallel"`，預設為 `"sequence"`。
- `cwd`：整批命令共用的工作目錄；`None` 使用目前工作目錄。
- `env`：整批命令共用的 child environment。`None` 繼承目前環境；傳入 mapping 時會作為完整 child environment，不會自動與 `os.environ` 合併。
- `encoding`：stdout/stderr 文字解碼，預設為 UTF-8。
- `errors`：解碼錯誤策略，預設為 `"replace"`。
- `output_limit`：每個程序、每個 channel 各自的保存上限，預設為 10 MiB；`None` 取消上限。
- `timeout`：每個程序從實際啟動起計算的最長秒數；`None` 不限制。

所有選項套用於整批命令，目前不支援 per-command overrides。

## Sequence 排程

`mode="sequence"` 的行為如下：

1. 所有命令完成預檢後，建立並註冊對應的 `ProcessObject`。
2. 第一個 subprocess 立即啟動，其餘 `ProcessObject` 保持 `pending`。
3. 排程 thread 等待目前程序完成。
4. exit code 為 `0` 時啟動下一個程序。
5. exit code 非 `0` 時，後續尚未啟動的程序全部標記為 `skipped`。

`skipped` 程序不會建立 subprocess，並具有以下結果：

- `status.state == "skipped"`
- `status.pid is None`
- `outcome.exit_code is None`
- `outcome.termination_reason == TerminationReason.SKIPPED`
- stdout/stderr 為空
- duration 為 `0.0`

如果 sequence 中後續 executable 無法啟動，該 `ProcessObject` 會進入 `failed`，其後項目標記為 `skipped`。如果第一個 executable 無法啟動，`run_external_process()` 直接拋出 `ProcessStartError`。

## Parallel 排程

`mode="parallel"` 會在預檢成功後啟動所有命令。各 subprocess 的生命週期互相獨立：

- 一個程序以非零 exit code 結束，不會停止 sibling processes。
- 每個程序分別保存 PID、status、stream、stdout、stderr 與 outcome。
- 可將回傳 list 直接傳給 `manager.display()` 或 `procpulse.display()`。

安全預檢是 atomic，但 OS process creation 不是 transaction。如果 parallel 啟動途中發生 `ProcessStartError`，已啟動的程序會繼續執行，尚未啟動的 pending 項目會標記為 `skipped`，呼叫端會收到例外。

## 命令安全預檢

ProcPulse 在建立任何 `ProcessObject` 或 subprocess 前，先檢查整批命令。任一命令包含禁止 token 時：

- 拋出 `UnsafeCommandError`
- 錯誤包含命令索引與第一個偵測到的 token
- `ProcessManager` 不會註冊該批程序
- 整批不會啟動任何 subprocess

檢查採 lexical policy，不解析 token 是否位於引號內。禁止 token 即使只是 quoted argument 的一部分也會被拒絕。

### Unix-like 禁止 token

```text
&&  ||  >>  <<  $(  |  ;  >  <  &  `  newline  carriage-return
```

### Windows 禁止 token

```text
&&  ||  >>  <<  |  ;  >  <  &  ^  `  $(  newline  carriage-return
```

命令通過預檢後使用平台相應的 `shlex.split()` 行為解析為 argv。

## 固定 subprocess 行為

`shell` 不是公開選項。所有程序固定使用：

```python
shell=False
stdin=subprocess.DEVNULL
stdout=subprocess.PIPE
stderr=subprocess.PIPE
text=True
```

stdout 與 stderr 由不同 reader threads 同時排空。事件進入同一個 stream queue，但保留 `channel`；最終 outcome 仍分開保存兩個 channel。

即使輸出超過 `output_limit`，reader threads 仍持續排空 pipes，以避免 subprocess 因 pipe buffer 滿而 deadlock。此時 `outcome.output_truncated` 為 `True`。

## Process lifecycle

目前可觀察到的 state：

- `pending`：已建立 `ProcessObject`，尚未建立 subprocess。
- `running`：subprocess 已啟動。
- `stopping`：正在執行 graceful termination 或 force-kill 流程。
- `finished`：subprocess 以 exit code `0` 完成。
- `failed`：subprocess 以非零 exit code 結束，或 executable 無法啟動。
- `skipped`：尚未啟動，因 sequence 前項失敗或排程取消而不再執行。

timeout 從每個 subprocess 實際啟動時開始計算。逾時與手動停止都先 graceful terminate，等待 grace period 後才 force kill 受控 process tree；output readers 排空後才建立最終 outcome。

## 已驗證行為

目前測試套件涵蓋：

- 單一命令字串回傳一個 `ProcessObject`
- 多命令字串正規化與裸 Python 解析
- 預設 sequence 與明確 parallel
- 不合法 mode 在啟動前被拒絕
- shell token 與 quoted token 的 atomic rejection
- Windows `^` token 規則
- sequence 順序執行與失敗後 skipped
- parallel failure 不影響 sibling
- batch 與既有 display 整合
- stdout/stderr stream、尾端輸出與 output truncation
- graceful stop、timeout、manager close 與未知 process ID
- macOS/Linux nested ProcPulse process-tree cleanup

最後核對時完整測試結果為：

```text
26 passed
```

Windows token 規則有跨平台單元測試；Windows Job Object 與 `taskkill` fallback 未在此次 macOS 執行環境中進行原生驗證。

## 已知限制與非目標

- 不支援 `shell=True`，也不自動啟動 `sh`、`bash`、`zsh`、`cmd.exe` 或 PowerShell。
- 不支援 pipeline、command chaining、redirection、background shell job、shell substitution 或 shell-specific environment assignment。
- lexical policy 會拒絕 quoted argument 中的禁止 token，可能包含原本只想當作資料傳遞的字元；這是刻意的保守行為。
- 不支援 per-command `cwd`、`env`、timeout、encoding 或 output limit。
- parallel 不提供 `fail_fast`，也不會在一個程序失敗時自動停止 siblings。
- 不合併多個程序為單一 PID、單一 outcome 或不分 channel 的 stream。
- Persistent CLI 尚未提供 sequence/parallel batch scheduling。
- process-tree 清理仍受權限、detached session、daemonization、service manager 與 PID reuse 等作業系統限制。
