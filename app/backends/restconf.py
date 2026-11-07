
"""RESTCONF interface backend."""

import os
import requests

from ipaddress import IPv4Interface, IPv4Network
from app.planner import build_plan


def get_interface_state(router, interface_name, http_get=None):
    """Return normalized interface status using RESTCONF."""

    url = (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={interface_name}"
    )

    try:
        if http_get is not None:
            response = http_get(url)
        else:
            response = requests.get(
                url,
                auth=(
                    os.getenv("ROUTER_USER", ""),
                    os.getenv("ROUTER_PASS", "")
                ),
                headers={
                    "Accept": "application/yang-data+json"
                },
                timeout=10,
                verify=False
            )

        if response.status_code == 404:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        if response.status_code in (401, 403):
            return {
                "status": "error",
                "result": "authentication_failed"
            }

        if response.status_code != 200:
            return {
                "status": "error",
                "result": "backend_failed"
            }

        data = response.json()

        interface = data.get("ietf-interfaces:interface")

        # รองรับกรณี Router คืน Interface เป็น List
        if isinstance(interface, list):
            interface = next(
                (
                    item for item in interface
                    if item.get("name") == interface_name
                ),
                None
            )

        if interface is None:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        if not isinstance(interface, dict):
            raise ValueError("Invalid interface data")

        # รองรับ Interface ที่ไม่มี IPv4
        ipv4_data = interface.get("ietf-ip:ipv4", {})
        addresses = ipv4_data.get("address", [])

        ipv4 = None

        if addresses:
            address = addresses[0]
            ip = address.get("ip")
            mask = address.get("netmask")

            if ip and mask:
                prefix = IPv4Network(
                    f"0.0.0.0/{mask}"
                ).prefixlen
                ipv4 = f"{ip}/{prefix}"

        # enabled ไม่มีค่า หมายถึงค่า Default เป็น Up
        enabled = interface.get("enabled", True)

        if isinstance(enabled, str):
            enabled = enabled.lower() != "false"

        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": interface.get("name", interface_name),
                "ipv4": ipv4,
                "description": interface.get("description"),
                "admin_state": "up" if enabled else "down"
            }
        }

    except PermissionError:
        return {
            "status": "error",
            "result": "authentication_failed"
        }

    except (
        ConnectionError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.SSLError
    ):
        return {
            "status": "error",
            "result": "connection_failed"
        }

    except Exception:
        return {
            "status": "error",
            "result": "backend_failed"
        }


def plan_interface(router, desired_interface, http_get=None):
    """Build a create/update/no_change plan using RESTCONF."""

    response = get_interface_state(
        router,
        desired_interface["name"],
        http_get=http_get
    )

    if response["status"] == "error":
        return response

    current_interface = response.get("interface")

    return build_plan(desired_interface, current_interface)


def apply_interface(router, desired_interface, http_put=None):
    """Apply complete desired interface state using RESTCONF."""

    try:
        name = desired_interface["name"]
        number = int(name[len("Loopback"):])

        ipv4 = IPv4Interface(desired_interface["ipv4"])
        ip = str(ipv4.ip)
        mask = str(ipv4.network.netmask)

        url = (
            f"https://{router}/restconf/data/"
            f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
        )

        loopback = {
            "name": number,
            "description": desired_interface["description"],
            "ip": {
                "address": {
                    "primary": {
                        "address": ip,
                        "mask": mask
                    }
                }
            }
        }

        if desired_interface["admin_state"] == "down":
            loopback["shutdown"] = [None]

        payload = {
            "Cisco-IOS-XE-native:Loopback": loopback
        }

        if http_put is not None:
            response = http_put(url, json=payload)
        else:
            response = requests.put(
                url,
                json=payload,
                auth=(
                    os.getenv("ROUTER_USER", ""),
                    os.getenv("ROUTER_PASS", "")
                ),
                headers={
                    "Accept": "application/yang-data+json",
                    "Content-Type": "application/yang-data+json"
                },
                timeout=10,
                verify=False
            )

        if response.status_code in (200, 201, 204):
            return {
                "status": "ok",
                "result": "applied"
            }

        if response.status_code in (401, 403):
            return {
                "status": "error",
                "result": "authentication_failed"
            }

        return {
            "status": "error",
            "result": "backend_failed"
        }

    except PermissionError:
        return {
            "status": "error",
            "result": "authentication_failed"
        }

    except (
        ConnectionError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.SSLError
    ):
        return {
            "status": "error",
            "result": "connection_failed"
        }

    except Exception:
        return {
            "status": "error",
            "result": "backend_failed"
        }
