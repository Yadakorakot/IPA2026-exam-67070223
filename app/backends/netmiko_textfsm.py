
"""Netmiko + TextFSM backend for Cisco IOS interfaces."""

import os
import re
from ipaddress import IPv4Address, IPv4Interface, IPv4Network


# ==========================================
# Normalize Interface Name
# ==========================================
def normalize_name(name):
    """Convert Lo123 to Loopback123."""

    name = str(name).strip()

    if name.lower().startswith("loopback"):
        return "Loopback" + name[8:]

    if name.lower().startswith("lo") and name[2:].isdigit():
        return "Loopback" + name[2:]

    return name


# ==========================================
# Error Handling
# ==========================================
def backend_error(exc):
    """Convert exceptions to required error results."""

    name = type(exc).__name__.lower()

    if (
        isinstance(exc, PermissionError)
        or "authentication" in name
        or "autherror" in name
    ):
        result = "authentication_failed"

    elif (
        isinstance(
            exc,
            (ConnectionError, TimeoutError, OSError)
        )
        or "timeout" in name
        or "connection" in name
        or "ssherror" in name
    ):
        result = "connection_failed"

    else:
        result = "backend_failed"

    return {
        "status": "error",
        "result": result
    }


# ==========================================
# SSH Connection
# ==========================================
def connect_router(router):
    """Connect to Cisco IOS using Netmiko."""

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


# ==========================================
# Helpers
# ==========================================
def _first(value):
    """Get first value from a TextFSM list."""

    if isinstance(value, list):
        return value[0] if value else ""

    return value


def _not_found_output(text):
    """Detect an explicitly missing interface."""

    text = str(text).lower()

    patterns = (
        "invalid interface",
        "interface does not exist",
        "interface not found",
        "no such interface",
        "not a valid interface",
    )

    return any(pattern in text for pattern in patterns)


def _command_error(text):
    """Detect IOS CLI command errors."""

    text = str(text).lower()

    patterns = (
        "% invalid input",
        "% incomplete command",
        "% ambiguous command",
        "% error",
    )

    return any(pattern in text for pattern in patterns)


def _admin_state(value):
    """Normalize Cisco administrative state."""

    text = str(_first(value) or "").strip().lower()

    if "administratively down" in text:
        return "down"

    if text in (
        "admin down",
        "disabled",
        "shutdown",
    ):
        return "down"

    return "up"


def _parse_ipv4(ip, prefix):
    """Convert IP and prefix/netmask to CIDR."""

    ip = str(_first(ip) or "").strip()
    prefix = str(_first(prefix) or "").strip()

    if not ip or ip.lower() in (
        "unassigned",
        "none",
        "unset",
    ):
        return None

    # รองรับ IP ที่มี /prefix มาแล้ว
    if "/" in ip:
        return str(IPv4Interface(ip))

    if not prefix:
        return None

    address = str(IPv4Address(ip))

    # Prefix อาจมาเป็น 24 หรือ 255.255.255.0
    if "." in prefix:
        prefix = IPv4Network(
            f"0.0.0.0/{prefix}"
        ).prefixlen

    prefix = int(prefix)

    if not 0 <= prefix <= 32:
        raise ValueError("Invalid prefix length")

    return f"{address}/{prefix}"


# ==========================================
# TextFSM / CLI Fallback Parser
# ==========================================
def _parse_ip_interface_fallback(output, target):
    """Parse show ip interface text if TextFSM fails."""

    text = str(output or "").strip()

    if not text:
        raise ValueError("Empty CLI output")

    if _not_found_output(text):
        return []

    if _command_error(text):
        raise ValueError("Cisco CLI command failed")

    lines = text.splitlines()
    header = None

    # ตัวอย่าง:
    # Loopback123 is up, line protocol is up
    # Loopback123 is administratively down,
    # line protocol is down
    for line in lines:
        match = re.match(
            r"^\s*(\S+)\s+is\s+(.+?)(?:,|$)",
            line,
            re.IGNORECASE,
        )

        if match:
            if normalize_name(match.group(1)) == target:
                header = match.group(2).strip()
                break

    # ไม่เจอ Header ไม่ควรเดาว่า Interface ไม่มี
    if header is None:
        raise ValueError("Cannot parse interface header")

    ip = ""
    prefix = ""

    # ตัวอย่าง:
    # Internet address is 10.1.1.1/24
    match = re.search(
        r"Internet address is\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})",
        text,
        re.IGNORECASE,
    )

    if match:
        ip = match.group(1)
        prefix = match.group(2)

    # บาง IOS แสดง:
    # Internet address is 10.1.1.1 255.255.255.0
    else:
        match = re.search(
            r"Internet address is\s+"
            r"(\d{1,3}(?:\.\d{1,3}){3})"
            r"\s+(\d{1,3}(?:\.\d{1,3}){3})",
            text,
            re.IGNORECASE,
        )

        if match:
            ip = match.group(1)
            prefix = match.group(2)

    return [{
        "interface": target,
        "ip_address": ip,
        "prefix_length": prefix,
        "link_status": header,
    }]


def _parse_descriptions_fallback(output):
    """Parse show interfaces description text."""

    text = str(output or "")

    if _command_error(text):
        raise ValueError("Cannot read interface descriptions")

    results = []

    # ตัวอย่าง:
    # Interface Status Protocol Description
    # Lo123     up     up       Test Loopback
    # Lo124     admin down down  Another Loopback
    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if line.lower().startswith("interface "):
            continue

        parts = re.split(r"\s{2,}", line, maxsplit=3)

        if len(parts) >= 3:
            name = parts[0]
            status = parts[1]
            protocol = parts[2]
            description = parts[3] if len(parts) > 3 else ""

            results.append({
                "interface": name,
                "status": status,
                "protocol": protocol,
                "description": description,
            })

    return results


def _normalize_ip_result(data, target):
    """Normalize TextFSM records or raw CLI text."""

    if isinstance(data, list):
        if not all(isinstance(item, dict) for item in data):
            raise ValueError("Invalid TextFSM IP records")

        return data

    if isinstance(data, str):
        return _parse_ip_interface_fallback(data, target)

    raise ValueError("Unsupported IP output type")


def _normalize_descriptions(data):
    """Normalize TextFSM descriptions or raw CLI text."""

    if isinstance(data, list):
        if not all(isinstance(item, dict) for item in data):
            raise ValueError("Invalid description records")

        return data

    if isinstance(data, str):
        return _parse_descriptions_fallback(data)

    raise ValueError("Unsupported description output type")


# ==========================================
# Read Interface State
# ==========================================
def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Read and normalize an interface state."""

    try:
        target = normalize_name(interface_name)

        # ----------------------------------
        # Fake Function for Public Tests
        # ----------------------------------
        if netmiko_get is not None:
            ip_info, descriptions = netmiko_get(
                router,
                interface_name
            )

        # ----------------------------------
        # Real Router via SSH
        # ----------------------------------
        else:
            connection = connect_router(router)

            try:
                ip_info = connection.send_command(
                    f"show ip interface {target}",
                    use_textfsm=True
                )

                descriptions = connection.send_command(
                    "show interfaces description",
                    use_textfsm=True
                )

            finally:
                connection.disconnect()

        ip_info = _normalize_ip_result(
            ip_info,
            target
        )

        descriptions = _normalize_descriptions(
            descriptions
        )

        # ----------------------------------
        # Find Interface
        # ----------------------------------
        found = None

        for item in ip_info:
            name = normalize_name(
                item.get("interface", "")
            )

            if name == target:
                found = item
                break

        # อ่าน Description และ Admin State
        description = None
        description_state = None
        description_found = False

        for item in descriptions:
            name = normalize_name(
                item.get(
                    "interface",
                    item.get("port", "")
                )
            )

            if name == target:
                description_found = True

                description = (
                    item.get("description") or None
                )

                description_state = item.get(
                    "status",
                    item.get("link_status", "")
                )

                break

        # ไม่พบทั้งสองคำสั่ง
        if found is None and not description_found:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        # ----------------------------------
        # IPv4
        # ----------------------------------
        ipv4 = None

        if found is not None:
            ip = found.get(
                "ip_address",
                found.get("ip", "")
            )

            prefix = found.get(
                "prefix_length",
                found.get("prefix", "")
            )

            ipv4 = _parse_ipv4(ip, prefix)

        # ----------------------------------
        # Administrative State
        # ----------------------------------
        if found is not None:
            state = found.get(
                "link_status",
                found.get("status", "")
            )
        else:
            state = ""

        # หาก IP Result ไม่มีสถานะ
        # ให้ใช้ Description แทน
        if not state and description_state:
            state = description_state

        admin_state = _admin_state(state)

        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": target,
                "ipv4": ipv4,
                "description": description,
                "admin_state": admin_state
            }
        }

    except Exception as exc:
        return backend_error(exc)


# ==========================================
# Delete Interface
# ==========================================
def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete interface through Netmiko SSH."""

    try:
        target = normalize_name(interface_name)

        # ----------------------------------
        # Fake Function for Public Tests
        # ----------------------------------
        if netmiko_delete is not None:
            result = netmiko_delete(
                router,
                interface_name
            )

        # ----------------------------------
        # Real Router
        # ----------------------------------
        else:
            # ตรวจสถานะด้วย Netmiko
            before = get_interface_state(
                router,
                target
            )

            if before["status"] == "error":
                return before

            if before["result"] == "not_found":
                return {
                    "status": "ok",
                    "result": "not_found",
                    "interface": None
                }

            connection = connect_router(router)

            try:
                output = connection.send_config_set(
                    [f"no interface {target}"]
                )

                if _command_error(output):
                    raise RuntimeError(
                        "Delete command failed"
                    )

            finally:
                connection.disconnect()

            # ตรวจว่าลบจริง
            after = get_interface_state(
                router,
                target
            )

            if after["status"] == "error":
                return after

            if after["result"] != "not_found":
                return {
                    "status": "error",
                    "result": "backend_failed"
                }

            result = "deleted"

        # ----------------------------------
        # Standard Results
        # ----------------------------------
        if result == "deleted":
            return {
                "status": "ok",
                "result": "deleted"
            }

        if result == "not_found":
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        return {
            "status": "error",
            "result": "backend_failed"
        }

    except Exception as exc:
        return backend_error(exc)
