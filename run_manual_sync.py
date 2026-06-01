import os
import sys
sys.path.insert(0, r'c:\מיצד\SchoolPoints')

# Import the sync agent module
import sync_agent
import json

# Load config
config_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'SchoolPoints', 'config.json')
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

db_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'SchoolPoints', 'school_points.db')

print("Running manual sync...")
print(f"Tenant ID: {config.get('sync_tenant_id')}")
print(f"API Key: {config.get('sync_api_key')[:10]}...")
print(f"Push URL: {config.get('sync_push_url')}")

# Run full sync cycle (push + pull)
result = sync_agent.run_full_cycle(
    db_path=db_path,
    push_url=config.get('sync_push_url'),
    api_key=config.get('sync_api_key'),
    tenant_id=config.get('sync_tenant_id'),
    station_id=config.get('sync_station_id', '')
)

print(f"\nSync Result: {result}")

# Also pull license data
import urllib.request
import urllib.parse

# Try to get license from cloud
license_url = config.get('sync_push_url', '').replace('/sync/push', '') + f"/api/institution/{config.get('sync_tenant_id')}/license"
print(f"\nChecking license at: {license_url}")

try:
    req = urllib.request.Request(
        license_url,
        headers={'api-key': config.get('sync_api_key')}
    )
    with urllib.request.urlopen(req) as resp:
        license_data = json.loads(resp.read())
        print(f"License Response: {license_data}")
except Exception as e:
    print(f"License check error: {e}")
