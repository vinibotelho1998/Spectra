import sys, os, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from spectra.core.protocol import OpenRGBClient, REQUEST_CONTROLLER_DATA

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
proto = int(sys.argv[2]) if len(sys.argv) > 2 else None

c = OpenRGBClient(name="Spectra-dump")
c.connect()
if proto is None:
    proto = c.protocol
print(f"servidor negociou v{c.protocol}, pedindo com v{proto}")
payload = c._request(idx, REQUEST_CONTROLLER_DATA, struct.pack("<I", proto))
print(f"payload = {len(payload)} bytes")
print()

for off in range(0, min(len(payload), 640), 16):
    chunk = payload[off:off + 16]
    hexs = " ".join(f"{b:02x}" for b in chunk)
    asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    print(f"{off:04x}  {hexs:<47}  {asc}")
c.close()
