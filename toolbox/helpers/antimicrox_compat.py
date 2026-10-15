"""Install the process-local Qt6 profile-reader registration shim."""
import base64
import hashlib
import os
from pathlib import Path
import sys
import tempfile

SHA256 = '8d40490cacb6fefcdd00b6a53b99057fe6158acbab6693ff8e89f32e713e3a63'
PAYLOAD = Path(__file__).resolve().parents[1]/'compat/antimicrox/register-xml-reader-x86_64.so.b64'


def install(destination, payload=PAYLOAD):
    destination = Path(destination)
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == SHA256:
        return
    data = base64.b64decode(Path(payload).read_bytes())
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('AntiMicroX Qt6 compatibility payload checksum mismatch')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.xml-reader-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(name, 0o644)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == '__main__':
    install(sys.argv[1])
