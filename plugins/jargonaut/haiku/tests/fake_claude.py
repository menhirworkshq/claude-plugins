#!/usr/bin/env python3
"""Stand-in for `claude -p --input-format stream-json` in the daemon tests.

FAKE_CLAUDE_MODE: echo (returns the segment in <out>), slow (never answers in
time), crash (exits on the first message), noout (answers without <out>), exit
(exits at once, like a logged-out claude).
FAKE_CLAUDE_COUNT: a file that gets 1 line per process started.
FAKE_CLAUDE_STARTUP_S: delay before the process reads stdin (claude startup).
"""
import json
import os
import re
import sys
import time

if os.environ.get("FAKE_CLAUDE_COUNT"):
    with open(os.environ["FAKE_CLAUDE_COUNT"], "a") as f:
        f.write("start\n")
time.sleep(float(os.environ.get("FAKE_CLAUDE_STARTUP_S", "0")))
mode = os.environ.get("FAKE_CLAUDE_MODE", "echo")
if mode == "exit":
    sys.exit(1)
cost = 0.0
for line in sys.stdin:
    msg = json.loads(line)["message"]["content"]
    if mode == "crash":
        sys.exit(1)
    if mode == "slow":
        time.sleep(30)
    segment = re.search(r"<segment>(.*)</segment>", msg, re.S).group(1)
    marker = " (ctx)" if "<previous_segments>" in msg else ""
    result = "I cannot help with that." if mode == "noout" else f"<out>{segment}{marker}</out>"
    cost += 0.0001
    print(json.dumps({"type": "assistant", "message": {}}), flush=True)
    print(json.dumps({"type": "result", "result": result, "total_cost_usd": cost,
                      "duration_api_ms": 10, "usage": {}}), flush=True)
