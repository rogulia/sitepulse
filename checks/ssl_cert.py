import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CertInfo:
    host: str
    expires: datetime | None
    days_left: int | None
    error: str | None = None


def check_certificate(host: str, port: int = 443, timeout: int = 10) -> CertInfo:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except ssl.SSLCertVerificationError as e:
        return CertInfo(host, None, None, f"certificate invalid: {e.verify_message}")
    except (OSError, ssl.SSLError) as e:
        return CertInfo(host, None, None, f"connection failed: {e}")

    expires = datetime.fromtimestamp(
        ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc
    )
    days_left = int((expires.timestamp() - time.time()) // 86400)
    return CertInfo(host, expires, days_left)
