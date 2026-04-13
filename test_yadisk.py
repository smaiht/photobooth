"""Test Yandex Disk WebDAV upload speed. Run: python test_yadisk.py"""

import base64, hashlib, time, os
from urllib.request import Request, urlopen

# Load .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

LOGIN = os.environ.get("YADISK_LOGIN", "")
PASSWORD = os.environ.get("YADISK_PASSWORD", "")

if not LOGIN or not PASSWORD:
    print("ERROR: YADISK_LOGIN or YADISK_PASSWORD not set in .env")
    exit(1)

AUTH = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
BASE = "https://webdav.yandex.ru/_traffic/photos_to_vps"

# Ensure folder exists
try:
    req = Request(f"{BASE}/", method="MKCOL", headers={"Authorization": f"Basic {AUTH}"})
    urlopen(req, timeout=10)
except Exception:
    pass

for size_mb in [1, 10, 30]:
    data = os.urandom(size_mb * 1024 * 1024)
    name = f"speedtest_{size_mb}mb.bin"
    url = f"{BASE}/{name}"

    print(f"\n--- {size_mb}MB upload ---")
    print(f"Uploading {len(data)} bytes...")

    start = time.time()
    try:
        req = Request(url, data=data, method="PUT", headers={
            "Authorization": f"Basic {AUTH}",
            "Content-Type": "application/binary",
            "Etag": hashlib.md5(data).hexdigest(),
            "Sha256": hashlib.sha256(data).hexdigest().upper(),
        })
        resp = urlopen(req, timeout=300)
        elapsed = time.time() - start
        speed = size_mb / elapsed
        print(f"OK ({resp.status}) in {elapsed:.1f}s = {speed:.1f} MB/s ({speed*8:.1f} Mbit/s)")
    except Exception as e:
        elapsed = time.time() - start
        print(f"FAILED after {elapsed:.1f}s: {e}")

    # Cleanup
    try:
        req = Request(url, method="DELETE", headers={"Authorization": f"Basic {AUTH}"})
        urlopen(req, timeout=10)
        print("Cleaned up")
    except Exception:
        pass

print("\nDone!")
input("Press Enter to close...")
