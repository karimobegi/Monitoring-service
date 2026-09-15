import ipaddress
import socket
from urllib.parse import urlsplit


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private          # 10/8, 172.16/12, 192.168/16, fc00::/7
        or ip.is_loopback      # 127/8, ::1
        or ip.is_link_local    # 169.254/16 — cloud metadata lives here
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified   # 0.0.0.0
    )


def resolves_to_blocked_address(hostname: str) -> bool:
    """True if any address the hostname resolves to is one we refuse to fetch.

    A hostname can be a literal IP, in which case getaddrinfo just parses it.
    DNS failure returns False: the check itself will report the failure, and
    refusing to save the endpoint would be a confusing error for a typo.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if is_blocked_ip(ip):
            return True
    return False