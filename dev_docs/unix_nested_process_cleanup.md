# Linux/macOS 巢狀程序清理設計

## 目的

讓外層 ProcPulse 在 Linux/macOS 上停止或逾時時，可以清理由內層 ProcPulse 建立的程序；同時避免內層呼叫 `stop()` 時誤殺外層程序或兄弟程序。

## Process group 模型

外層 ProcPulse 建立 root process 時使用 `start_new_session=True`，建立獨立 process group。啟動的子程序會收到內部環境變數：

```text
PROCPULSE_PROCESS_GROUP=1
```

如果子程序內再次使用 ProcPulse，內層 Unix backend 偵測到這個環境變數後，不再建立新的 session，而是繼承外層 process group：

```text
Process A：root process group G
└── Process B：nested ProcPulse，繼承 G
    └── Process C：繼承 G
```

這讓外層可以使用 `killpg(G, signal)` 清理整個受控範圍。

## Backend ownership

Unix backend 必須記錄自己是否擁有 process group：

- root backend：擁有自己建立的 process group，可使用 `killpg()`。
- nested backend：不擁有 process group，不可使用 `killpg()`，避免終止外層或兄弟程序。

### Root process 的停止

root process 使用以下流程：

1. 對整個 process group 發送 `SIGTERM`。
2. 等待 grace period。
3. 仍存活時，對整個 process group 發送 `SIGKILL`。

### Nested process 的停止

nested process 使用 `psutil.Process(pid).children(recursive=True)` 取得自身 descendants：

1. 先對 descendants 發送 `SIGTERM`。
2. 對 nested 主程序發送 `SIGTERM`。
3. 等待 grace period。
4. 仍存活時，依 descendants 的反向順序發送 `SIGKILL`。
5. 最後強制終止 nested 主程序。

不使用 nested process 所繼承的 process group，避免把外層程序與兄弟程序一起終止。

## 環境變數與安全性

ProcPulse 會將控制環境變數加入子程序的 environment。若呼叫端傳入 `env`，仍保留其明確設定，並在傳遞給子程序前加入 ProcPulse 的內部 marker。

環境變數只用來判斷 process group inheritance，不作為唯一的程序識別依據。清理 descendants 時仍以作業系統回報的 parent-child 關係為準，並處理程序已經退出或 PID 已被重用的例外。

## 已知限制

如果外部程式主動呼叫 `setsid()`、daemonize、轉交給 systemd/launchd，或因權限不同而脫離控制範圍，ProcPulse 無法保證清理成功。這些情況必須回報清理結果，而不是宣稱所有 descendants 都已終止。

## 測試要求

- root process 可清理一般子程序與多層 descendants。
- nested ProcPulse 的 process 可被外層 stop/timeout 清理。
- nested ProcPulse 自己停止時，不會終止外層或兄弟程序。
- graceful termination 後仍存活的 descendants 會被 force kill。
- 程序已退出、PID 不存在或權限不足時，不會讓清理執行緒無限等待。
- Linux 與 macOS 都執行上述 process-tree 測試。
