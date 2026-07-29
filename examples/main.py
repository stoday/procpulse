from procpulse import ProcessManager

manager = ProcessManager()
process_1 = manager.run_external_process(
    'python examples/hello.py'
)

process_2 = manager.run_external_process('git status')

manager.display([process_1, process_2])

for index, process in enumerate((process_1, process_2), start=1):
    print(f"[process_{index}][outcome] {process.outcome}", flush=True)

manager.close()
