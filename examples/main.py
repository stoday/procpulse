from procpulse import ProcessManager

manager = ProcessManager()
processes = manager.run_external_process(
    ['python examples/hello.py', 'git status'],
    mode='parallel',
)

manager.display(processes)

for index, process in enumerate(processes, start=1):
    print(f"[process_{index}] **outcome** {process.outcome}", flush=True)

manager.close()
