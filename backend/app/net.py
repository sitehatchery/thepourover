"""HTTP clients for calls the API makes to other services (Google, OpenAI).

Python connects to each resolved address in turn rather than racing them like browsers do. On a network
with a broken IPv6 route, every call to a dual-stack host then waits for the IPv6 attempts to time out
(observed: 20s+ per Google call). Binding to the IPv4 wildcard address makes connections go over IPv4.
Set CDP_OUTBOUND_IPV4_ONLY=false on hosts with working IPv6.
"""

import httpx

from app.config import get_settings

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def outbound_transport() -> httpx.HTTPTransport:
    if get_settings().outbound_ipv4_only:
        return httpx.HTTPTransport(local_address="0.0.0.0", retries=1)
    return httpx.HTTPTransport(retries=1)


def outbound_client(timeout: httpx.Timeout | float = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(transport=outbound_transport(), timeout=timeout)
