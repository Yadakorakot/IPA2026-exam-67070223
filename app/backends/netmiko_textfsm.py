
"""Netmiko + TextFSM backend for Cisco IOS."""

import logging
import os
import re

from ipaddress import IPv4Address, IPv4Interface, IPv4Network

logger = logging.getLogger(__name__)


def normalize_name(name):
    name = str(name or "").strip()

    if name.lower().startswith("loopback"):
        return "Loopback" + name[8:]

    if name.lower().startswith("lo") and name[2:].isdigit():
        return "Loopback" + name[2:]

    return name


def backend_error(exc):
    name = type(exc).__name__.lower()

    logger.error(
        "Netmiko error: %s: %s",
        type(exc).__name__,
        exc,
    )

    if (
        isinstance(exc, PermissionError)
        or "authentication" in name
        or "autherror" in name
    ):
        result = "authentication_failed"

    elif (
        isinstance(exc, (ConnectionError, TimeoutError, OSError))
        or "timeout" in name
        or "connection" in name
        or "ssherror" in name
    ):
        result = "connection_failed"

    else:
        result = "backend_failed"

    return {"status": "error", "result": result}


def connect_router(router):
    from netmiko import ConnectHandler

    return ConnectHandler(
        device_type="cisco_ios",
        host=router,
        username=os.getenv("ROUTER_USER", ""),
        password=os.getenv("ROUTER_PASS", ""),
        port=22,
        conn_timeout=10,
        auth_timeout=10,
    )


def _first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def _parse_ipv4(item):
    ip = str(_first(item.get("ip_address", "")) or "").strip()
    prefix = str(_first(item.get("prefix_length", "")) or "").strip()

    if not ip or ip.lower() in ("unassigned", "none"):
        return None

    if "/" in ip:
        return str(IPv4Interface(ip))

    if not prefix:
        return None

    address = str(IPv4Address(ip))

    if "." in prefix:
        prefix = IPv4Network(
            f"0.0.0.0/{prefix}"
        ).prefixlen

    prefix = int(prefix)

    if not 0 <= prefix <= 32:
        raise ValueError("Invalid IPv4 prefix")

    return f"{address}/{prefix}"


def _parse_raw_ip(raw, interface_name):
    """Fallback parser for show ip interface."""

    text = str(raw or "").strip()
    target = normalize_name(interface_name)

    if not text:
        raise ValueError("Empty CLI output")

    if any(word in text.lower() for word in (
        "invalid input",
        "invalid interface",
        "does not exist",
        "no such interface",
    )):
        return []

    header = re.search(
        r"(?im)^\s*(\S+)\s+is\s+"
        r"(administratively down|up|down)"
        r"(?:,|\s*$)",
        text,
    )

    if not header:
        raise ValueError("Cannot parse interface header")

    if normalize_name(header.group(1)) != target:
        raise ValueError("Unexpected interface name")

    match = re.search(
        r"Internet address is\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3})"
        r"/(\d{1,2})",
        text,
        re.IGNORECASE,
    )

    ip = ""
    prefix = ""

    if match:
        ip, prefix = match.groups()

    else:
        match = re.search(
            r"Internet address is\s+"
            r"(\d{1,3}(?:\.\d{1,3}){3})\s+"
            r"(\d{1,3}(?:\.\d{1,3}){3})",
            text,
            re.IGNORECASE,
        )

        if match:
            ip, prefix = match.groups()

    return [{
        "interface": target,
        "ip_address": [ip] if ip else [],
        "prefix_length": [prefix] if prefix else [],
        "link_status": header.group(2),
    }]


def _parse_raw_descriptions(raw):
    """Fallback parser for show interfaces description."""

    results = []

    for line in str(raw or "").splitlines():
        line = line.strip()

        if not line or line.lower().startswith("interface "):
            continue

        match = re.match(
            r"^(\S+)\s+"
            r"(administratively down|admin down|up|down)"
            r"\s+(up|down)\s*(.*)$",
            line,
            re.IGNORECASE,
        )

        if match:
            results.append({
                "interface": match.group(1),
                "port": match.group(1),
                "status": match.group(2),
                "description": match.group(4).strip(),
            })

    return results


def _real_get(router, interface_name):
    """Read raw CLI first to avoid Netmiko TextFSM exceptions."""

    target = normalize_name(interface_name)
    connection = connect_router(router)

    try:
        raw_ip = connection.send_command(
            f"show ip interface {target}",
            use_textfsm=False,
        )

        raw_desc = connection.send_command(
            "show interfaces description",
            use_textfsm=False,
        )

    finally:
        connection.disconnect()

    # Attempt TextFSM on raw output.
    try:
        from ntc_templates.parse import parse_output

        ip_info = parse_output(
            platform="cisco_ios",
            command="show ip interface",
            data=raw_ip,
        )

    except Exception:
        logger.warning("TextFSM IP parse failed; using fallback")
        ip_info = None

    if not ip_info:
        ip_info = _parse_raw_ip(raw_ip, target)

    try:
        from ntc_templates.parse import parse_output

        descriptions = parse_output(
            platform="cisco_ios",
            command="show interfaces description",
            data=raw_desc,
        )

    except Exception:
        logger.warning(
            "TextFSM description parse failed; using fallback"
        )
        descriptions = None

    if descriptions is None:
        descriptions = _parse_raw_descriptions(raw_desc)

    return ip_info, descriptions


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface state."""

    try:
        target = normalize_name(interface_name)

        if netmiko_get is not None:
            ip_info, descriptions = netmiko_get(
                router,
                interface_name,
            )
        else:
            ip_info, descriptions = _real_get(
                router,
                interface_name,
            )

        if not isinstance(ip_info, list):
            raise ValueError("Invalid IP records")

        if not isinstance(descriptions, list):
            raise ValueError("Invalid description records")

        found = None

        for item in ip_info:
            if not isinstance(item, dict):
                raise ValueError("Invalid IP record")

            if normalize_name(item.get("interface")) == target:
                found = item
                break

        if found is None:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None,
            }

        ipv4 = _parse_ipv4(found)

        description = None
        description_status = ""

        for item in descriptions:
            if not isinstance(item, dict):
                continue

            name = item.get("interface") or item.get("port")

            if normalize_name(name) == target:
                description = item.get("description") or None
                description_status = str(
                    item.get("status") or ""
                ).lower()
                break

        link_status = str(
            found.get("link_status")
            or found.get("status")
            or description_status
        ).lower()

        admin_state = (
            "down"
            if (
                "administratively down" in link_status
                or "admin down" in link_status
                or link_status == "shutdown"
            )
            else "up"
        )

        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": target,
                "ipv4": ipv4,
                "description": description,
                "admin_state": admin_state,
            },
        }

    except Exception as exc:
        logger.exception("Netmiko status failed")
        return backend_error(exc)


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete interface using SSH; keep proven RESTCONF checks."""

    try:
        if netmiko_delete is not None:
            result = netmiko_delete(router, interface_name)

        else:
            from app.backends.restconf import (
                get_interface_state as check_state
            )

            target = normalize_name(interface_name)

            before = check_state(router, target)

            if before["status"] == "error":
                return before

            if before["result"] == "not_found":
                return {
                    "status": "ok",
                    "result": "not_found",
                    "interface": None,
                }

            connection = connect_router(router)

            try:
                output = connection.send_config_set(
                    [f"no interface {target}"]
                )

                if any(word in str(output).lower() for word in (
                    "% invalid",
                    "% error",
                    "% incomplete",
                    "% ambiguous",
                )):
                    raise RuntimeError("Delete command rejected")

            finally:
                connection.disconnect()

            after = check_state(router, target)

            if after["status"] == "error":
                return after

            if after["result"] != "not_found":
                logger.error(
                    "Interface still exists after delete: %s",
                    target,
                )
                return {
                    "status": "error",
                    "result": "backend_failed",
                }

            result = "deleted"

        if result == "deleted":
            return {
                "status": "ok",
                "result": "deleted",
            }

        if result == "not_found":
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None,
            }

        return {
            "status": "error",
            "result": "backend_failed",
        }

    except Exception as exc:
        logger.exception("Netmiko delete failed")
        return backend_error(exc)
