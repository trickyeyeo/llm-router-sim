#!/usr/bin/env python3
"""
Test the actual running backend API to see what data it returns.
"""

import requests
import json
from urllib.parse import urlencode

BASE_URL = "http://localhost:8000"

# Graceful Degradation demo params
params_baseline = {
    "num_sessions": 20,
    "turns_per_session": 2,
    "failure_rate": 0.2,
    "network_type": "rdma",
    "enable_p2p_recovery": "false",
}

params_with_p2p = {
    "num_sessions": 20,
    "turns_per_session": 2,
    "failure_rate": 0.2,
    "network_type": "rdma",
    "enable_p2p_recovery": "true",
}

print("=" * 70)
print("TESTING ACTUAL BACKEND API")
print("=" * 70)
print()

# Test baseline
print("1. Running BASELINE simulation via API...")
url = f"{BASE_URL}/simulate?{urlencode(params_baseline)}"
print(f"   URL: {url}")
print()

try:
    response = requests.get(url, stream=True, timeout=60)
    print(f"   Status: {response.status_code}")

    baseline_complete_data = None
    event_count = 0

    for line in response.iter_lines():
        if line:
            event_count += 1
            try:
                data = json.loads(line.decode('utf-8').replace('data: ', ''))
                if data.get('type') == 'complete':
                    baseline_complete_data = data
                    print(f"   Received complete event")
            except:
                pass

    print(f"   Total events: {event_count}")
    print()

    if baseline_complete_data:
        print("   BASELINE FINAL DATA:")
        stateful = baseline_complete_data.get('stateful', {})
        print(f"   - Has 'gpus' field: {'gpus' in stateful}")
        if 'gpus' in stateful:
            gpus = stateful['gpus']
            print(f"   - gpu0: blocks={gpus.get('gpu0', {}).get('num_cached_blocks', '?')}, hits={gpus.get('gpu0', {}).get('cache_hit_rate', '?')}")
            print(f"   - gpu1: blocks={gpus.get('gpu1', {}).get('num_cached_blocks', '?')}, hits={gpus.get('gpu1', {}).get('cache_hit_rate', '?')}")
        else:
            print("   - GPU metrics NOT in response")
            print(f"   - Top-level keys: {list(stateful.keys())}")

except Exception as e:
    print(f"   ERROR: {e}")

print()
print("=" * 70)
