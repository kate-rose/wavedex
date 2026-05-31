"""
RTL-SDR connection config.

Direct USB mode (Mac):   RTL_TCP_HOST unset
TCP client mode (Tab):   RTL_TCP_HOST=127.0.0.1  RTL_TCP_PORT=1234 (default)

The SDR Driver app on Android exposes the dongle as an rtl_tcp server on
localhost:1234. Set RTL_TCP_HOST=127.0.0.1 in the Termux environment and
all decoders will route through it instead of touching USB directly.
"""

import os

RTL_TCP_HOST: str | None = os.environ.get("RTL_TCP_HOST")
RTL_TCP_PORT: int = int(os.environ.get("RTL_TCP_PORT", "1234"))

def using_tcp() -> bool:
    return RTL_TCP_HOST is not None
