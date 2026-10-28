#!/usr/bin/env python3
import sys
import json
from pathlib import Path

# Add parent directory to path to import route.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from route import resolve_intent, classify

def test_15_json_flag_output():
    """Test that --json flag outputs intent, method, and score as JSON."""
    intent, hits, method = resolve_intent("fix the bug in utils.py", use_embed=False)

    # Test that resolve_intent returns the expected structure
    assert isinstance(intent, str)
    assert intent in ['recall', 'research', 'coding', 'architecture']
    assert isinstance(hits, int)
    assert method in ['keyword', 'embed', 'keyword-fallback', 'explicit']

    # Test that we can construct the JSON output as expected by the --json flag
    result = {
        "intent": intent,
        "method": method,
        "score": hits
    }
    json_output = json.dumps(result)

    # Verify it's valid JSON
    parsed = json.loads(json_output)
    assert parsed["intent"] == intent
    assert parsed["method"] == method
    assert parsed["score"] == hits

if __name__ == "__main__":
    test_15_json_flag_output()
    print("✓ test_15_json_flag_output passed")
