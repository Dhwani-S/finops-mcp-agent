"""Quick backend test for 3 demo queries via the SSE chat API."""
import requests
import json
import sys

BASE = "http://localhost:8000"

def clear_session(session_id="test"):
    r = requests.post(f"{BASE}/api/clear", json={"session_id": session_id})
    print(f"[clear] {r.status_code}")

def send_query(message, session_id="test"):
    """Send a chat message and collect all SSE events."""
    print(f"\n{'='*80}")
    print(f"QUERY: {message}")
    print('='*80)
    
    r = requests.post(
        f"{BASE}/api/chat",
        json={"message": message, "session_id": session_id},
        headers={"Accept": "text/event-stream"},
        stream=True,
    )
    
    events = []
    tool_calls = []
    tool_results = []
    final_text = ""
    plan = None
    elicitation = None
    
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("event:"):
            event_type = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_str = line.split(":", 1)[1].strip()
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = data_str
            
            events.append({"event": event_type, "data": data})
            
            if event_type == "thinking":
                print(f"  [thinking] {data.get('message', '')}")
            elif event_type == "plan":
                plan = data.get("goals", [])
                statuses = [f"{g.get('label','?')[:40]}({g.get('status','?')})" for g in plan]
                print(f"  [plan] {statuses}")
            elif event_type == "tool_call":
                tool_name = data.get("tool", "?")
                args = data.get("args", {})
                # Truncate args for display
                args_str = json.dumps(args, default=str)
                if len(args_str) > 200:
                    args_str = args_str[:200] + "..."
                print(f"  [tool_call] {tool_name}({args_str})")
                tool_calls.append(data)
            elif event_type == "tool_result":
                tool_name = data.get("tool", "?")
                chars = data.get("chars", 0)
                result = data.get("result", "")
                # Show first 300 chars of result
                preview = result[:300].replace('\n', ' ')
                print(f"  [tool_result] {tool_name} ({chars} chars): {preview}")
                tool_results.append(data)
            elif event_type == "text":
                content = data.get("content", "")
                final_text = content
                print(f"  [text] {content[:500]}")
            elif event_type == "elicitation":
                elicitation = data
                print(f"  [elicitation] {json.dumps(data)[:200]}")
            elif event_type == "error":
                print(f"  [ERROR] {data}")
            elif event_type == "done":
                rounds = data.get("rounds", "?")
                print(f"  [done] rounds={rounds}")
    
    print(f"\nSUMMARY: {len(tool_calls)} tool calls, {len(tool_results)} results, text={len(final_text)} chars")
    if elicitation:
        print(f"ELICITATION: {json.dumps(elicitation)[:300]}")
    
    return events, final_text, elicitation


def test_query(query_num, message, session_id=None):
    """Test a single query with auto-approve to skip cost confirmations."""
    sid = session_id or f"test-q{query_num}"
    
    # Clear session first
    clear_session(sid)
    
    # Set auto-approve to skip dry-run cost confirmations
    send_query("accept all for session", session_id=sid)
    
    # Send the actual query with scope context
    # Simulate having the "Jehan Demo" scope (owner: Jehan Wickramasuriya)
    scoped_message = f"[scope: owner=Jehan Wickramasuriya, name=Jehan Demo]\n{message}"
    events, text, elicitation = send_query(scoped_message, session_id=sid)
    
    # If we got an elicitation (asking for confirmation), send "yes"
    if elicitation or "shall i proceed" in text.lower() or "scan approximately" in text.lower():
        print("\n--- Got cost confirmation, sending 'yes' ---")
        events2, text2, elicitation2 = send_query("yes, proceed", session_id=sid)
        return events + events2, text2
    
    return events, text


if __name__ == "__main__":
    query_num = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    
    queries = [
        "Run a VM and disk rightsizing analysis on my Azure resources",
        "Compare my top AWS EC2 instances against equivalent Azure and GCP VMs",
        "What if we migrate my top 5 AWS workloads to GCP? Show estimated cost impact",
    ]
    
    if query_num == 0:
        # Run all
        for i, q in enumerate(queries, 1):
            print(f"\n\n{'#'*80}")
            print(f"# TEST QUERY {i}")
            print(f"{'#'*80}")
            test_query(i, q)
    else:
        test_query(query_num, queries[query_num - 1])
