
import os
import requests
from ipaddress import IPv4Interface, IPv4Network

from app.planner import build_plan


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""

    # URL สำหรับอ่าน Interface ผ่าน IETF YANG
    url = (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={interface_name}"
    )

    try:
        if http_get is not None:
            # ใช้ HTTP จำลองสำหรับ Tests
            response = http_get(url)
        else:
            # ติดต่อ Router จริง
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
                verify=False  # ใช้กับ Router Lab เท่านั้น
            )

        # ไม่พบ Interface
        if response.status_code == 404:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        # Username หรือ Password ไม่ถูกต้อง
        if response.status_code in (401, 403):
            return {
                "status": "error",
                "result": "authentication_failed"
            }

        # HTTP Status อื่นที่ไม่สำเร็จ
        if response.status_code != 200:
            return {
                "status": "error",
                "result": "backend_failed"
            }

        # อ่าน JSON ที่ Router ส่งกลับ
        data = response.json()
        interface = data["ietf-interfaces:interface"]

        # แปลง IPv4 + Netmask เป็น CIDR
        address = interface["ietf-ip:ipv4"]["address"][0]
        ip = address["ip"]
        mask = address["netmask"]

        prefix = IPv4Network(
            f"0.0.0.0/{mask}"
        ).prefixlen

        # แปลงข้อมูลเป็นรูปแบบมาตรฐาน
        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": interface["name"],
                "ipv4": f"{ip}/{prefix}",
                "description": interface.get("description"),
                "admin_state": (
                    "up" if interface["enabled"] else "down"
                )
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


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""

    # อ่านสถานะปัจจุบันจาก RESTCONF
    response = get_interface_state(
        router,
        desired_interface["name"],
        http_get=http_get
    )

    # ถ้าอ่าน Router ไม่สำเร็จ ให้ส่ง Error กลับ
    if response["status"] == "error":
        return response

    # ถ้าไม่พบ Interface ให้ใช้ None
    if response["result"] == "not_found":
        current_interface = None
    else:
        current_interface = response["interface"]

    # ใช้ Planner จาก Part 2
    return build_plan(
        desired_interface,
        current_interface
    )


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""

    try:
        # ดึงหมายเลข Loopback เช่น Loopback123 -> 123
        name = desired_interface["name"]
        number = int(name[len("Loopback"):])

        # แปลง IP/CIDR เป็น IP และ Netmask
        ipv4 = IPv4Interface(
            desired_interface["ipv4"]
        )

        ip = str(ipv4.ip)
        mask = str(ipv4.network.netmask)

        # URL สำหรับเขียน Cisco Native YANG
        url = (
            f"https://{router}/restconf/data/"
            f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
        )

        # สร้าง Payload สำหรับ PUT
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

        # ถ้าต้องการปิด Interface
        if desired_interface["admin_state"] == "down":
            loopback["shutdown"] = [None]

        payload = {
            "Cisco-IOS-XE-native:Loopback": loopback
        }

        if http_put is not None:
            # ใช้ HTTP จำลองสำหรับ Tests
            response = http_put(
                url,
                json=payload
            )
        else:
            # ส่ง PUT ไป Router จริง
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
                verify=False  # ใช้กับ Router Lab เท่านั้น
            )

        # HTTP Success
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
