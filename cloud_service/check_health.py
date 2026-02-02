import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8000/health') as response:
        print(response.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
