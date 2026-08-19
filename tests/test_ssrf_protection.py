"""Tests for SSRF protection module."""

import pytest
from unittest.mock import patch

from nexus.governance.ssrf_protection import SSRFGuard


@pytest.fixture
def guard() -> SSRFGuard:
    """Create an SSRFGuard instance for testing."""
    return SSRFGuard()


class TestIsSafeIp:
    """Tests for SSRFGuard.is_safe_ip()."""

    def test_public_ipv4_is_safe(self, guard: SSRFGuard) -> None:
        """Public IPv4 addresses should be considered safe."""
        assert guard.is_safe_ip("8.8.8.8") is True
        assert guard.is_safe_ip("1.1.1.1") is True
        assert guard.is_safe_ip("93.184.216.34") is True

    def test_block_0_0_0_0_slash_8(self, guard: SSRFGuard) -> None:
        """Addresses in 0.0.0.0/8 should be blocked."""
        assert guard.is_safe_ip("0.0.0.0") is False
        assert guard.is_safe_ip("0.255.255.255") is False

    def test_block_10_slash_8(self, guard: SSRFGuard) -> None:
        """Addresses in 10.0.0.0/8 should be blocked."""
        assert guard.is_safe_ip("10.0.0.1") is False
        assert guard.is_safe_ip("10.255.255.255") is False

    def test_block_100_64_slash_10(self, guard: SSRFGuard) -> None:
        """Addresses in 100.64.0.0/10 (carrier-grade NAT) should be blocked."""
        assert guard.is_safe_ip("100.64.0.1") is False
        assert guard.is_safe_ip("100.127.255.255") is False

    def test_block_127_slash_8(self, guard: SSRFGuard) -> None:
        """Loopback addresses (127.0.0.0/8) should be blocked."""
        assert guard.is_safe_ip("127.0.0.1") is False
        assert guard.is_safe_ip("127.255.255.255") is False

    def test_block_169_254_slash_16(self, guard: SSRFGuard) -> None:
        """Link-local addresses (169.254.0.0/16) should be blocked."""
        assert guard.is_safe_ip("169.254.0.1") is False
        assert guard.is_safe_ip("169.254.169.254") is False

    def test_block_172_16_slash_12(self, guard: SSRFGuard) -> None:
        """Addresses in 172.16.0.0/12 should be blocked."""
        assert guard.is_safe_ip("172.16.0.1") is False
        assert guard.is_safe_ip("172.31.255.255") is False

    def test_block_192_168_slash_16(self, guard: SSRFGuard) -> None:
        """Addresses in 192.168.0.0/16 should be blocked."""
        assert guard.is_safe_ip("192.168.0.1") is False
        assert guard.is_safe_ip("192.168.255.255") is False

    def test_block_224_slash_3(self, guard: SSRFGuard) -> None:
        """Multicast/reserved addresses (224.0.0.0/3) should be blocked."""
        assert guard.is_safe_ip("224.0.0.1") is False
        assert guard.is_safe_ip("255.255.255.255") is False
        assert guard.is_safe_ip("240.0.0.1") is False

    def test_block_ipv6_loopback(self, guard: SSRFGuard) -> None:
        """IPv6 loopback (::1) should be blocked."""
        assert guard.is_safe_ip("::1") is False

    def test_block_ipv6_unspecified(self, guard: SSRFGuard) -> None:
        """IPv6 unspecified address (::) should be blocked."""
        assert guard.is_safe_ip("::") is False

    def test_block_ipv6_ula(self, guard: SSRFGuard) -> None:
        """IPv6 unique local addresses (fc00::/7) should be blocked."""
        assert guard.is_safe_ip("fc00::1") is False
        assert guard.is_safe_ip("fd00::1") is False

    def test_block_ipv6_link_local(self, guard: SSRFGuard) -> None:
        """IPv6 link-local (fe80::/10) should be blocked."""
        assert guard.is_safe_ip("fe80::1") is False

    def test_block_ipv6_site_local(self, guard: SSRFGuard) -> None:
        """IPv6 site-local (fec0::/10) should be blocked."""
        assert guard.is_safe_ip("fec0::1") is False

    def test_block_ipv6_multicast(self, guard: SSRFGuard) -> None:
        """IPv6 multicast (ff00::/8) should be blocked."""
        assert guard.is_safe_ip("ff02::1") is False

    def test_public_ipv6_is_safe(self, guard: SSRFGuard) -> None:
        """Public IPv6 addresses should be considered safe."""
        assert guard.is_safe_ip("2001:4860:4860::8888") is True

    def test_ipv4_mapped_ipv6_blocked(self, guard: SSRFGuard) -> None:
        """IPv4-mapped IPv6 addresses should be de-mapped and checked."""
        assert guard.is_safe_ip("::ffff:127.0.0.1") is False
        assert guard.is_safe_ip("::ffff:7f00:1") is False
        assert guard.is_safe_ip("::ffff:10.0.0.1") is False

    def test_ipv4_mapped_ipv6_safe(self, guard: SSRFGuard) -> None:
        """Safe IPv4-mapped IPv6 addresses should pass."""
        assert guard.is_safe_ip("::ffff:8.8.8.8") is True

    def test_cloud_metadata_ip_blocked(self, guard: SSRFGuard) -> None:
        """Cloud metadata IP (169.254.169.254) should be blocked."""
        assert guard.is_safe_ip("169.254.169.254") is False

    def test_unparseable_ip_fails_closed(self, guard: SSRFGuard) -> None:
        """Unparseable IP addresses should fail closed (return False)."""
        assert guard.is_safe_ip("not-an-ip") is False
        assert guard.is_safe_ip("") is False
        assert guard.is_safe_ip("999.999.999.999") is False


class TestSafeResolve:
    """Tests for SSRFGuard.safe_resolve()."""

    @pytest.mark.asyncio
    async def test_resolve_safe_host(self, guard: SSRFGuard) -> None:
        """Resolving a host with only public IPs should return safe=True."""
        mock_result = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=mock_result):
            result = await guard.safe_resolve("example.com")
        assert result["safe"] is True
        assert "93.184.216.34" in result["addresses"]

    @pytest.mark.asyncio
    async def test_resolve_blocked_host(self, guard: SSRFGuard) -> None:
        """Resolving a host with any private IP should return safe=False."""
        mock_result = [
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=mock_result):
            result = await guard.safe_resolve("internal.corp")
        assert result["safe"] is False

    @pytest.mark.asyncio
    async def test_resolve_mixed_addresses(self, guard: SSRFGuard) -> None:
        """If ANY address is blocked, the whole resolution is unsafe."""
        mock_result = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=mock_result):
            result = await guard.safe_resolve("dual-homed.example.com")
        assert result["safe"] is False

    @pytest.mark.asyncio
    async def test_resolve_failure(self, guard: SSRFGuard) -> None:
        """DNS resolution failure should return safe=False."""
        import socket as sock_mod

        with patch(
            "socket.getaddrinfo", side_effect=sock_mod.gaierror("DNS failed")
        ):
            result = await guard.safe_resolve("nonexistent.invalid")
        assert result["safe"] is False
        assert result["addresses"] == []

    @pytest.mark.asyncio
    async def test_resolve_deduplicates_addresses(
        self, guard: SSRFGuard
    ) -> None:
        """Duplicate addresses should be deduplicated."""
        mock_result = [
            (2, 1, 6, "", ("8.8.8.8", 0)),
            (2, 2, 17, "", ("8.8.8.8", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=mock_result):
            result = await guard.safe_resolve("dns.google")
        assert result["safe"] is True
        assert result["addresses"] == ["8.8.8.8"]


class TestIsSafeUrl:
    """Tests for SSRFGuard.is_safe_url()."""

    def test_https_is_always_safe(self, guard: SSRFGuard) -> None:
        """HTTPS URLs are always acceptable."""
        assert guard.is_safe_url("https://example.com/path") is True
        assert guard.is_safe_url("https://10.0.0.1/admin") is True

    def test_http_localhost_allowed(self, guard: SSRFGuard) -> None:
        """HTTP is allowed for localhost."""
        assert guard.is_safe_url("http://localhost/api") is True
        assert guard.is_safe_url("http://localhost:8080/") is True

    def test_http_127_0_0_1_allowed(self, guard: SSRFGuard) -> None:
        """HTTP is allowed for 127.0.0.1."""
        assert guard.is_safe_url("http://127.0.0.1/api") is True
        assert guard.is_safe_url("http://127.0.0.1:3000/") is True

    def test_http_ipv6_loopback_allowed(self, guard: SSRFGuard) -> None:
        """HTTP is allowed for ::1."""
        assert guard.is_safe_url("http://[::1]/api") is True

    def test_http_remote_blocked(self, guard: SSRFGuard) -> None:
        """HTTP to non-localhost hosts should be blocked."""
        assert guard.is_safe_url("http://example.com/path") is False
        assert guard.is_safe_url("http://10.0.0.1/admin") is False

    def test_ftp_blocked(self, guard: SSRFGuard) -> None:
        """Non-HTTP/HTTPS protocols should be blocked."""
        assert guard.is_safe_url("ftp://example.com/file") is False

    def test_empty_and_invalid(self, guard: SSRFGuard) -> None:
        """Empty and invalid URLs should be blocked."""
        assert guard.is_safe_url("") is False
        assert guard.is_safe_url("not-a-url") is False
