"""La guardia del browser blocca le stesse reti della guardia Python.

Con una sessione interattiva Python l'indirizzo di un link non lo vede mai: il
modello clicca, Chromium naviga, e l'unico strato che vede dove porta un click,
un redirect o una sottorisorsa e' ``JennyBrowserBridge.isBlockedAddress``. Le sue
reti devono essere quelle di ``jafta/security/network.py::_BLOCKED_NETWORKS``;
la versione Kotlin era rimasta indietro e lasciava passare ``::127.0.0.1``
(IPv4-compatibile, che ``isLoopbackAddress`` non riconosce), il multicast, il
broadcast, e un IPv4 locale dentro un NAT64 (``64:ff9b::/96``) o un 6to4
(``2002::/16``).

Il Kotlin in CI non gira: si legge il codice (``support.kotlin_source``), e ogni
rete di Python deve avere il suo riscontro nella funzione.
"""

from __future__ import annotations

import ipaddress
import re

from support.kotlin_source import function_body, read_code, read_source

from jafta.security import network

# Come il Kotlin copre ogni rete IPv6 di Python: l'API di InetAddress o un
# controllo sui byte. Una rete nuova in Python senza voce qui fa fallire il test:
# e' il promemoria di allineare il Kotlin.
_V6_COVERAGE = {
    "::1/128": ("isLoopbackAddress",),
    "fe80::/10": ("isLinkLocalAddress",),
    "fc00::/7": ("(b[0].toInt() and 0xFE) == 0xFC",),
    # Su un Inet6Address, isSiteLocalAddress e' proprio fec0::/10.
    "fec0::/10": ("addr.isSiteLocalAddress",),
    "::ffff:0:0:0/96": (
        "(0..7).all { b[it] == 0.toByte() } && b[8] == 0xFF.toByte()",
        "b[10] == 0.toByte() && b[11] == 0.toByte()) return true",
    ),
    "64:ff9b:1::/48": ("b[4] == 0x00.toByte() && b[5] == 0x01.toByte()) return true",),
    "::/96": ("(0..11).all { b[it] == 0.toByte() }",),
    "ff00::/8": ("isMulticastAddress",),
    "64:ff9b::/96": ("b[3] == 0x9B.toByte()", "embeddedIpv4(b)"),
    "2002::/16": ("b[1] == 0x02.toByte()", "embeddedIpv4(b)"),
}


def _blocked_v4_in_kotlin() -> set[ipaddress.IPv4Network]:
    src = read_source("JennyBrowserBridge")
    block = src[src.index("private val BLOCKED_V4 = listOf(") :]
    block = block[: block.index("\n        )")]
    return {
        ipaddress.ip_network(f"{net}/{bits}")
        for net, bits in re.findall(r'"([\d.]+)" to (\d+)', block)
    }


def _guard() -> str:
    code = read_code("JennyBrowserBridge")
    return function_body(code, "isBlockedAddress") + function_body(code, "embeddedIpv4")


def test_every_python_ipv4_network_is_blocked_by_the_browser() -> None:
    kotlin = _blocked_v4_in_kotlin()
    guard = _guard()
    missing = []
    for net in network._BLOCKED_NETWORKS:
        if net.version != 4 or net in kotlin:
            continue
        if net == ipaddress.ip_network("224.0.0.0/4") and "addr.isMulticastAddress" in guard:
            continue
        missing.append(str(net))
    assert not missing, f"reti IPv4 di Python che il browser lascia passare: {missing}"


def test_every_python_ipv6_network_has_its_counterpart() -> None:
    guard = _guard()
    unknown, missing = [], []
    for net in network._BLOCKED_NETWORKS:
        if net.version != 6:
            continue
        needles = _V6_COVERAGE.get(str(net))
        if needles is None:
            unknown.append(str(net))
        elif not all(n in guard for n in needles):
            missing.append(str(net))
    assert not unknown, f"reti IPv6 nuove in Python, da portare nel Kotlin: {unknown}"
    assert not missing, f"reti IPv6 di Python che il browser lascia passare: {missing}"


def test_the_forms_that_carry_an_ipv4_are_judged_by_that_ipv4() -> None:
    """NAT64, 6to4 e IPv4-mapped: il verdetto e' quello dell'IPv4 dentro."""
    guard = _guard()
    for needle in (
        "addr.isMulticastAddress",
        "(0..11).all { b[it] == 0.toByte() }",
        "embeddedIpv4(b)?.let { return isBlockedAddress(InetAddress.getByAddress(it)) }",
    ):
        assert needle in guard, needle
    embedded = function_body(read_code("JennyBrowserBridge"), "embeddedIpv4")
    # mapped (::ffff:a.b.c.d) e NAT64 (64:ff9b::a.b.c.d): gli ultimi 4 byte.
    assert embedded.count("b.copyOfRange(12, 16)") == 2
    assert "b[10] == 0xFF.toByte() && b[11] == 0xFF.toByte()" in embedded
    assert "b[0] == 0x00.toByte() && b[1] == 0x64.toByte() && b[2] == 0xFF.toByte()" in embedded
    # 6to4 (2002:AABB:CCDD::): i byte 2..5.
    assert "b[0] == 0x20.toByte() && b[1] == 0x02.toByte() -> b.copyOfRange(2, 6)" in embedded
    assert ipaddress.ip_network("255.255.255.255/32") in _blocked_v4_in_kotlin()
