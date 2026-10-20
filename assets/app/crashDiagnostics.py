"""Keep a fault-log descriptor alive for native failures, including spawn workers."""
import faulthandler
import os
from pathlib import Path


_fault_file = None


def enable_fault_log(directory):
    global _fault_file
    if _fault_file is not None:
        return
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        _fault_file = (directory / f"python_fault_{os.getpid()}.log").open("a", encoding="utf-8")
        faulthandler.enable(file=_fault_file, all_threads=True)
    except (OSError, RuntimeError):
        if _fault_file is not None:
            _fault_file.close()
            _fault_file = None
        # Diagnostics must not prevent launching the application.
