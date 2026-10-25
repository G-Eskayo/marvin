import json, sys, time, os
p = os.path.expanduser("~/.agents/logs/parakeet-150.jsonl")
while not os.path.exists(p): time.sleep(1)
f = open(p)
while True:
    line = f.readline()
    if not line:
        time.sleep(1); continue
    try: e = json.loads(line)
    except Exception: print(line.rstrip()); continue
    if e.get("type") == "assistant":
        for c in e["message"].get("content", []):
            if c.get("type") == "text": print("\n" + c["text"])
            elif c.get("type") == "tool_use":
                i = c.get("input", {})
                print("  > " + c["name"] + ": " + str(i.get("description") or i.get("command") or i.get("file_path") or "")[:150])
    elif e.get("type") == "result":
        print("\n=== DONE ===\n" + str(e.get("result", ""))[:3000])
    sys.stdout.flush()
