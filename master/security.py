import hashlib
import hmac
import ipaddress
import re
import secrets
import socket
from urllib.parse import urlsplit


class BusinessError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(data, key, max_length=2048):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > max_length:
        raise BusinessError("Invalid " + key)
    return value.strip()


def integer(value, minimum=1, maximum=1000):
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise BusinessError("Expected an integer")
    number = int(value)
    if not minimum <= number <= maximum:
        raise BusinessError("Value out of range")
    return number


def username(value):
    if not re.fullmatch(r"[A-Za-z0-9]{2,24}", value):
        raise BusinessError("Username must contain 2-24 letters or digits")
    return value


def subdomain(value):
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise BusinessError("Invalid route prefix")
    return value


def hostname(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if len(value) > 253 or any(
            not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in value.split(".")
        ):
            raise BusinessError("Invalid node host")
        return value.lower()


def target_url(value, resolve=False):
    if not value or len(value) > 2048 or re.search(r'[\s"\'\\;$`{}]', value):
        raise BusinessError("Invalid origin URL")
    try:
        parsed = urlsplit(value if "://" in value else "https://" + value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        if parsed.fragment:
            raise ValueError()
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError()
        host = hostname(parsed.hostname)
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            ] if resolve else []
        if any(not address.is_global for address in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise BusinessError("Origin must use a public HTTP(S) address")
    return parsed.geturl()


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240000).hex()
    return "pbkdf2_sha256$240000$" + salt + "$" + digest


def password_verify(password, stored):
    if not password or not stored:
        return False
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt, digest = stored.split("$")
            iterations = int(rounds)
            if iterations < 100000 or iterations > 1000000:
                return False
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
            return hmac.compare_digest(actual, digest)
        except (ValueError, TypeError):
            return False
    legacy = hashlib.sha256(password.encode()).hexdigest()
    fixed_salt = hashlib.pbkdf2_hmac("sha256", password.encode(), b"emby-panel-v1", 240000).hex()
    return hmac.compare_digest(stored, legacy) or hmac.compare_digest(stored, fixed_salt)
