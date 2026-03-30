#!/usr/bin/env python3

import json
import subprocess
import time


def run_once() -> dict:
    raw = subprocess.check_output(
        ["python3", "scripts/generate_insight_weekly_report.py", "--days", "7"],
        text=True,
    )
    return json.loads(raw)


def main() -> None:
    while True:
        data = run_once()
        print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)
        if bool(data.get("ready_for_decision")):
            print("READY_FOR_DECISION", flush=True)
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
