"""SSRF Protection - guards against server-side request forgery attacks.

Validates URLs and IP addresses against known private/reserved network ranges
to prevent internal network access from user-controlled inputs.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFGuard:
    """Guard against Server-Side Request Forgery (SSRF) attacks.

    Provides methods to validate IP addresses, resolve hostnames safely,
    and enforce URL protocol policies to prevent access to internal networks.
    """

    BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
        # IPv4 reserved/private ranges
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("224.0.0.0/3"),
        # IPv6 reserved/private ranges
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("::/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("fec0::/10"),
        ipaddress.ip_network("ff00::/8"),
    ]

    def is_safe_ip(self, ip_str: str) -> bool:
        """Check whether an IP address is safe (not in any blocked range).

        Handles IPv4-mapped IPv6 addresses by de-mapping them before checking.
        If the address cannot be parsed, fails closed (returns False).

        Args:
            ip_str: The IP address string to validate.

        Returns:
            True if the IP is safe (public), False if blocked or unparseable.
        """
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        # De-map IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped

        for network in self.BLOCKED_NETWORKS:
            if addr in network:
                return False
        return True

    async def safe_resolve(self, hostname: str) -> dict[str, bool | list[str]]:
        """Resolve a hostname and check ALL returned addresses for safety.

        Uses socket.getaddrinfo to resolve the hostname, then validates
        every returned address against blocked networks.

        Args:
            hostname: The hostname to resolve.

        Returns:
            A dict with 'safe' (bool) and 'addresses' (list of resolved IPs).
            If ANY address is blocked, 'safe' is False.
        """
        try:
            infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
        except (socket.gaierror, OSError):
            return {"safe": False, "addresses": []}

        addresses: list[str] = []
        for info in infos:
            addr = info[4][0]
            if addr not in addresses:
                addresses.append(addr)

        safe = all(self.is_safe_ip(addr) for addr in addresses)
        return {"safe": safe, "addresses": addresses}

    def is_safe_url(self, url_str: str) -> bool:
        """Validate URL protocol enforcement.

        HTTPS is required for remote hosts. HTTP is only allowed
        for localhost, 127.0.0.1, and ::1.

        Args:
            url_str: The URL string to validate.

        Returns:
            True if the URL protocol is acceptable, False otherwise.
        """
        try:
            parsed = urlparse(url_str)
        except Exception:
            return False

        scheme = parsed.scheme.lower()
        hostname = parsed.hostname or ""

        if scheme == "https":
            return True

        if scheme == "http":
            localhost_hosts = {"localhost", "127.0.0.1", "::1"}
            return hostname in localhost_hosts

        return False


def guard_url(url_str: str, field: str = "url") -> str:
    """Reject a URL that violates SSRF policy (scheme or literal private IP).

    Fails closed. DNS is not resolved here — hostname resolution happens at
    request time, so use SSRFGuard.safe_resolve for that leg.

    Args:
        url_str: The URL to check.
        field: Config key name, used in the error message.

    Returns:
        The URL unchanged, when it is allowed.

    Raises:
        ValueError: If the URL is blocked by SSRF policy.
    """
    guard = SSRFGuard()
    if not guard.is_safe_url(url_str):
        raise ValueError(f"{field} blocked by SSRF protection: {url_str}")

    hostname = (urlparse(url_str).hostname or "").strip("[]")
    # is_safe_url deliberately permits loopback (local dev backends such as
    # Ollama); do not re-block it here.
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return url_str
    # A literal IP in the URL skips DNS entirely, so check it now.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return url_str  # hostname, not a literal IP
    if not guard.is_safe_ip(hostname):
        raise ValueError(f"{field} blocked by SSRF protection: {url_str}")
    return url_str
