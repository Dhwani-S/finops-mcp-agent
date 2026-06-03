"""Debug query 2 - Cross-cloud VM comparison"""
import requests, json

BASE = "http://localhost:8000"
SID = "debug2"

requests.post(f"{BASE}/api/clear", json={"session_id": SID})

# auto-approve
r = requests.post(f"{BASE}/api/chat", json={"message": "accept all for session", "session_id": SID}, headers={"Accept": "text/event-stream"}, stream=True)
for line in r.iter_lines(decode_unicode=True): pass

# Actual query
r = requests.post(
    f"{BASE}/api/chat",
    json={
        "message": "[scope: owner=Jehan Wickramasuriya, name=Jehan Demo]\nCompare my top AWS EC2 instances against equivalent Azure and GCP VMs",
        "session_id": SID,
    },
    headers={"Accept": "text/event-stream"},
    stream=True,
)

for line in r.iter_lines(decode_unicode=True):
    if not line:
        continue
    if line.startswith("event:"):
        etype = line.split(":", 1)[1].strip()
    elif line.startswith("data:"):
        raw = line.split(":", 1)[1].strip()
        data = json.loads(raw)
        if etype == "tool_call":
            tool = data.get("tool", "?")
            args = data.get("args", {})
            print(f"TOOL: {tool}")
            print(f"FULL SQL:\n{args.get('sql', args.get('scenario_json', json.dumps(args)))}")
            print("---")
        elif etype == "tool_result":
            chars = data.get("chars", 0)
            result = data.get("result", "")
            print(f"RESULT ({chars} chars): {result[:800]}")
            print("---")
        elif etype == "text":
            content = data.get("content", "")
            print(f"FINAL TEXT:\n{content[:2000]}")
        elif etype == "error":
            print(f"ERROR: {data}")
