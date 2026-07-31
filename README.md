# ProcPulse

ProcPulse 是一個跨平台的外部命令與程序管理工具，提供 Python API 與 CLI。
它可以執行與監控 Python、git、ls、npm、shell script、compiled binary 等任意可執行命令，並提供同步事件串流、程序狀態查詢、timeout，以及受控 process tree 的停止與清理。

目前支援 Linux、macOS 與 Windows。

執行依賴包含 `psutil`，用於 Linux/macOS 的 nested process descendants 清理。

ProcPulse 同時提供 Python API 與 CLI。CLI 適合需要跨多次命令呼叫觀察或停止長時間程序的情境。

## 功能

- 合併 stdout/stderr 的即時事件流，並保留輸出來源 `channel`。
- 追蹤程序狀態、PID、執行時間與 return code。
- 先 graceful terminate，逾時後 force kill。
- Linux/macOS 使用 process group；Windows 優先使用 Job Object，建立或加入失敗時 fallback 到 `taskkill /T /F` 清理程序樹。
- 可設定 timeout、工作目錄、環境變數、輸出編碼與輸出保存上限。
- stdout 與 stderr 在最終結果中分開保存。

## 安裝

在專案根目錄執行：

```bash
python3 -m pip install -e .
```

如果已啟用虛擬環境，也可以使用：

```bash
python -m pip install -e .
```

需要 Python 3.10 或更新版本。

## 快速開始

```python
import sys

from procpulse import ProcessManager

manager = ProcessManager()
process = manager.run_external_process(
    "python -c \"print('hello from ProcPulse', flush=True)\"",
)[0]

for event in process.stream:
    print(f"[{event.channel}] {event.text.rstrip()}")

print(process.outcome)
manager.close()
```

## Persistent CLI

使用 `start` 在背景啟動程序；它會立即回傳 `process_id`，之後可用其他 CLI 命令查詢或停止：

```bash
procpulse start -- python long_running.py
```

它也可以執行其他命令：

```bash
procpulse start -- git status
procpulse start -- ls -la
procpulse start -- npm test
procpulse start -- ./build.sh
```

查詢狀態：

```bash
procpulse status <process_id>
```

查看 stdout 或 stderr：

```bash
procpulse output <process_id>
procpulse output <process_id> --stderr
procpulse display <process_id_1> <process_id_2>
```

`display` 會同時讀取指定程序的 stdout/stderr 並定期顯示狀態；已完成程序只顯示一次，全部程序完成後返回。

停止程序：

```bash
procpulse stop <process_id> --grace-period 2
```

列出已知程序：

```bash
procpulse list
```

`list` 會列出每個被管理程序的：

- process ID、state、PID、uptime
- 實際 command 與 working directory
- exit code 與 termination reason
- stdout/stderr 保存位置

CLI 的 record 與輸出預設保存於「目標程序的 working directory」下的 `.procpulse/`；例如在 `/project` 執行命令，就會使用 `/project/.procpulse/`。可用 `PROCPULSE_HOME` 指定其他目錄。`start` 會由 background monitor 持有程序生命週期，因此 Agent 可以先啟動命令，再透過後續的 `status`、`output` 與 `stop` 命令判斷是否需要中斷。

清理已完成或失敗的 record 與輸出檔：

```bash
procpulse clean
```

`clean` 不會刪除仍在執行中的程序資料。若 `start` 使用了 `--cwd`，後續的 `status`、`output`、`stop` 與 `clean` 應在同一個 `.procpulse` 目錄下執行，或使用相同的 `PROCPULSE_HOME`。

在尚未安裝 editable package 時，也可以使用：

```bash
python3 -m procpulse start -- python long_running.py
```

也可以使用文件中描述的建立函式：

```python
from procpulse import process_manager

manager = process_manager.build()
```

## 即時事件流

`process.stream` 是同步、單次消費的 iterator。每筆事件是 `StreamEvent`，包含：

```python
event.channel    # "stdout" 或 "stderr"
event.text       # 該行文字
event.timestamp  # timezone-aware UTC datetime
```

stdout 與 stderr 會進入同一個事件流，但在 `process.outcome` 中仍會分開保存。
程序結束後，iterator 會繼續交付 pipe 中尚未讀取的尾端輸出，排空後才結束。

```python
for event in process.stream:
    if event.channel == "stderr":
        print(f"錯誤輸出: {event.text}")
    else:
        print(f"一般輸出: {event.text}")
```

第一版的事件流是單次消費，不支援多個 consumer 同時訂閱同一個 stream。

## 批次執行

`run_external_process()` 接受單一完整命令字串或多個命令字串。每個命令會對應一個獨立的 `ProcessObject`，回傳值是依輸入順序排列的 process 清單：

```python
processes = manager.run_external_process(
    ["python prepare.py", "python build.py"],
    mode="sequence",
)
```

`mode` 預設為 `"sequence"`。sequence 只有在前一個程序成功後才會啟動下一個；如果其中一個程序失敗，後續命令會標記為 `skipped`，不會建立 subprocess。

需要同時執行互相獨立的命令時，指定 `mode="parallel"`：

```python
processes = manager.run_external_process(
    ["python lint.py", "python test.py"],
    mode="parallel",
)
manager.display(processes)
```

parallel 中某個程序失敗不會自動停止其他程序。每個 process 的 `status`、`stream`、PID 與 `outcome` 都保持獨立。

所有命令會在啟動前先完成安全預檢。ProcPulse 不支援在命令字串中使用 pipe、命令串接、重導向或其他 shell 控制語法，例如 `|`、`&&`、`||`、`;`、`>`、`<`。即使 token 位於引號中也會拒絕，並拋出 `UnsafeCommandError`；請將命令拆開交給 ProcPulse，以 sequence 或 parallel 表達工作流。

## 同時顯示多個程序

如果需要同時顯示 Manager 管理的多個程序事件與狀態，可以使用 `manager.display()`；它會在內部並行消費各程序的 stream，直到全部程序完成：

```python
from procpulse import ProcessManager

manager = ProcessManager()
processes = manager.run_external_process(
    ["python examples/hello.py", "python examples/hello.py"],
    mode="parallel",
)

manager.display(processes)
manager.close()
```

輸出會包含程序序號、channel 與定期狀態。狀態會先列出已完成的程序，再列出尚在執行的程序：

```text
[status]
  completed:
    process_2: state=finished, alive=False, pid=123, uptime=3.0s, cmd=/path/to/python examples/hello.py
  active:
    process_1: state=running, alive=True, pid=122, uptime=5.5s, cmd=/path/to/python examples/hello.py
```

可用 `status_interval` 調整狀態更新間隔。

若只需要顯示特定程序，也可以傳入程序清單；不傳入參數時，會顯示 Manager 目前追蹤的全部程序：

```python
manager.display(status_interval=1.0)
```

`manager.display()` 會阻塞直到指定的程序全部完成。原本的 `procpulse.display([...])` 便利函式仍然保留。

當所有程序都已完成時，`manager.display()` 只會輸出一次 completed 狀態，不會繼續定時刷新；它仍會排空並顯示尚未交付的尾端事件。

如果傳入的程序在呼叫 `display()` 前就已經完成，ProcPulse 只會顯示一次 completed 狀態，不會再次消費該程序的 single-consumer stream；完整輸出可從 `process.outcome.stdout` 與 `process.outcome.stderr` 取得。

## 狀態與結果

執行期間可讀取 `process.status`：

```python
status = process.status
status.state       # starting / running / stopping / finished / failed
status.is_alive
status.pid
status.uptime
status.return_code
status.cmd       # 實際執行的 immutable command tuple
status.work_dir  # 實際使用的絕對工作目錄
```

程序結束後，`process.outcome` 會提供：

```python
outcome.stdout
outcome.stderr
outcome.exit_code
outcome.duration
outcome.termination_reason
outcome.output_truncated
```

`ProcessOutcome` 提供 `to_string()` 產生適合閱讀的多行結果；直接使用 `print(outcome)` 也會使用相同格式：

```python
print(process.outcome.to_string())
```

輸出範例：

```text
ProcessOutcome:
  termination_reason: completed
  exit_code: 0
  duration: 0.123s
  output_truncated: False
  stdout:
    hello
  stderr:
    (empty)
```

`termination_reason` 可能是：

- `completed`：程序以 exit code 0 正常完成。
- `failed`：程序啟動失敗或以非零 exit code 結束。
- `cancelled`：由呼叫端停止。
- `timeout`：超過設定的執行時間。
- `killed`：graceful termination 無效後被強制終止。

## 停止程序與 timeout

`stop()` 預設先等待程序自行結束，等待時間預設為 2 秒；仍未結束時，才會強制終止受控 process tree。

```python
result = manager.stop(process.id, grace_period=2.0)

result.graceful
result.force_killed
result.tree_clean
```

也可以在啟動時設定 timeout：

```python
process = manager.run_external_process(
    "python -c \"import time; time.sleep(60)\"",
    timeout=10,
)[0]
```

timeout 會使用相同的 graceful terminate → force kill 流程，最終結果的停止原因會是 `timeout`。

## 啟動選項

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

參數說明：

- `command`：單一完整命令字串，或由多個完整命令字串組成的 sequence。單一字串也會回傳只含一個 `ProcessObject` 的清單；多個命令的回傳順序與輸入順序相同。所有命令會先通過安全預檢，再解析成 argument list。
- `mode`：批次排程方式，允許 `"sequence"` 或 `"parallel"`，預設為 `"sequence"`。sequence 會等待前一個命令成功後才啟動下一個；失敗後尚未啟動的命令會標記為 `skipped`。parallel 會啟動所有命令，單一程序失敗不會自動停止其他程序。
- `cwd`：所有命令共用的工作目錄，可傳入字串、path-like object 或 `None`。`None` 表示使用目前工作目錄；`ProcessStatus.work_dir` 會保存實際使用的絕對路徑。
- `env`：所有命令共用的 child-process environment mapping。`None` 表示繼承目前程序的環境；傳入 mapping 時會將它作為 child process 的完整環境，不會自動與 `os.environ` 合併。
- `encoding`：stdout 與 stderr 的文字解碼編碼，預設為 `"utf-8"`。
- `errors`：stdout 與 stderr 解碼錯誤的處理策略，直接傳給 Python 的文字解碼器，預設為 `"replace"`。
- `output_limit`：每個程序、每個 channel 各自保存的最大 byte 數，預設為 10 MiB。超過上限後仍會持續排空 pipe，以避免 subprocess deadlock，但超出的內容不會完整保留，且 `ProcessOutcome.output_truncated` 會是 `True`。設為 `None` 可取消上限。
- `timeout`：每個程序從實際啟動起計算的最長執行秒數。`None` 表示不限制；逾時時會先 graceful terminate，超過 grace period 後再 force kill 受控 process tree，最終 termination reason 為 `timeout`。

回傳值為 `list[ProcessObject]`。每個元素分別提供自己的 `id`、`status`、`stream`、`wait()`、`stop()` 與 `outcome`。

`shell` 不是公開啟動選項。ProcPulse 固定使用 argument list、`shell=False` 與 `stdin=DEVNULL`，並將 stdout/stderr 設為 pipe 以供串流與結果保存。這項限制讓 ProcPulse 能清楚管理每個 subprocess、輸出 channel 與 process tree。

當 `command` 使用未帶路徑的 `python`、`python3`、`python.exe` 或
`python3.exe` 時，ProcPulse 會自動改用目前執行 ProcPulse 的
`sys.executable`。這只是 Python launcher 的便利處理，不限制其他命令；例如：

```python
processes = manager.run_external_process(
    ["python script.py", "git status", "ls -la"],
    mode="sequence",
)
```

也可以將 executable 與參數放在同一個 command 字串中：

```python
process = manager.run_external_process("python examples/hello.py")[0]
```

ProcPulse 會將字串解析成 argument list，仍以 `shell=False` 執行，不會透過 shell 執行整段字串。命令字串中的 shell 控制語法（例如 `|`、`&&`、`||`、`;`、`>`、`<`）會被拒絕，即使它們出現在引號內也一樣。需要串接或平行執行時，請將每個命令分開傳入，並使用 `mode="sequence"` 或 `mode="parallel"`。

若指定了明確路徑，例如 `/usr/bin/python3`，ProcPulse 會保留該路徑，不會替換。

## 管理多個程序

```python
running = manager.list(filter="running")
all_processes = manager.list()

for process in running:
    print(process.id, process.status.uptime)
```

Manager 關閉後不能啟動新程序。`close(wait=True)` 會等待已追蹤程序完成並排空輸出；關閉 Manager 不會自動停止仍在執行的程序，請先明確呼叫 `stop()`。

## 錯誤處理

```python
from procpulse import (
    ManagerClosedError,
    ProcessNotFoundError,
    ProcessStartError,
    UnsafeCommandError,
)

try:
    process = manager.run_external_process("missing-command")
except ProcessStartError as exc:
    print(f"無法啟動程序: {exc}")
```

主要例外包括：

- `ProcessStartError`：外部程序無法啟動。
- `ProcessNotFoundError`：Manager 找不到指定的程序 ID。
- `ManagerClosedError`：Manager 已關閉。
- `ProcessTreeTerminationError`：無法完成受控 process tree 的終止。
- `UnsafeCommandError`：命令包含 ProcPulse 不支援的 shell 控制語法。

## 開發與測試

建立 editable installation：

```bash
python3 -m pip install -e .
```

執行測試：

```bash
python3 -m pytest -q
```

測試涵蓋事件流、尾端輸出、輸出限制、graceful stop、timeout、啟動失敗與 Manager 生命週期。

## Codex Skill

本專案也提供一個可版本控制的 Codex skill，位於：

```text
skills/process-execution-control/
```

它提供 ProcPulse 的 API 使用、外部程序生命週期、跨平台 process tree、nested process、display 與除錯指引。

要安裝到 Codex 的 skills 目錄，請執行：

```bash
mkdir -p ~/.codex/skills
cp -R skills/process-execution-control ~/.codex/skills/
```

更新 skill 時，重新執行上述複製指令即可。安裝後可在對話中使用：

```text
$process-execution-control
```

## 限制

ProcPulse 只能保證清理它建立並控制的 process group 或 Job Object 範圍。若外部程序脫離該範圍、需要更高權限，或轉交給作業系統服務管理，清理可能失敗；此時應檢查 `StopResult.tree_clean` 與相關例外。

第一版公開 API 以同步使用為主，尚未提供 async API。
