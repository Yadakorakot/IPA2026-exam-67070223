
"""NETCONF interface backend."""

import os
import xml.etree.ElementTree as ET

from ipaddress import IPv4Interface, IPv4Network
from app.planner import build_plan


# Namespace ของ YANG Models
IETF = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IETF_IP = "urn:ietf:params:xml:ns:yang:ietf-ip"
NATIVE = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"
NETCONF = "urn:ietf:params:xml:ns:netconf:base:1.0"


def backend_error(exc):
    """Convert NETCONF exceptions to standardized errors."""

    name = type(exc).__name__.lower()

    # ข้อผิดพลาดเกี่ยวกับ Username/Password
    if (
        isinstance(exc, PermissionError)
        or "authentication" in name
        or "autherror" in name
    ):
        result = "authentication_failed"

    # ข้อผิดพลาดเกี่ยวกับ Network/SSH
    elif (
        isinstance(exc, (ConnectionError, TimeoutError, OSError))
        or "timeout" in name
        or "connection" in name
        or "ssherror" in name
        or "transporterror" in name
        or "sessionclose" in name
        or "socketerror" in name
    ):
        result = "connection_failed"

    # ข้อผิดพลาดอื่นจาก NETCONF
    else:
        result = "backend_failed"

    return {
        "status": "error",
        "result": result
    }


def connect_router(router):
    """Connect to Cisco IOS XE using NETCONF over SSH."""

    from ncclient import manager

    return manager.connect(
        host=router,
        port=830,
        username=os.getenv("ROUTER_USER", ""),
        password=os.getenv("ROUTER_PASS", ""),
        hostkey_verify=False,
        allow_agent=False,
        look_for_keys=False,
        timeout=10
    )


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""

    try:
        # สร้าง XML Filter เพื่ออ่าน Interface ที่ต้องการ
        root = ET.Element(
            f"{{{IETF}}}interfaces"
        )

        interface = ET.SubElement(
            root,
            f"{{{IETF}}}interface"
        )

        ET.SubElement(
            interface,
            f"{{{IETF}}}name"
        ).text = interface_name

        filter_xml = ET.tostring(
            root,
            encoding="unicode"
        )

        # ใช้ Fake Function สำหรับ Public Tests
        if netconf_get_config is not None:
            xml_data = netconf_get_config(
                router,
                filter_xml
            )

        else:
            # ติดต่อ Router จริงผ่าน NETCONF Port 830
            with connect_router(router) as connection:
                reply = connection.get_config(
                    source="running",
                    filter=("subtree", filter_xml)
                )

                xml_data = reply.data_xml

        # แปลง XML เป็น Element
        xml_root = ET.fromstring(xml_data)

        namespaces = {
            "if": IETF,
            "ip": IETF_IP
        }

        # ค้นหา Interface ที่ชื่อตรงกัน
        found = None

        for item in xml_root.findall(
            ".//if:interface",
            namespaces
        ):
            name = item.findtext(
                "if:name",
                namespaces=namespaces
            )

            if name == interface_name:
                found = item
                break

        # ถ้าไม่มี Interface
        if found is None:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        # อ่านชื่อ
        name = found.findtext(
            "if:name",
            namespaces=namespaces
        )

        # อ่าน Description
        description = found.findtext(
            "if:description",
            namespaces=namespaces
        )

        # อ่านสถานะ Enabled
        enabled = found.findtext(
            "if:enabled",
            namespaces=namespaces
        )

        # อ่าน IPv4 Address
        ip = found.findtext(
            "ip:ipv4/ip:address/ip:ip",
            namespaces=namespaces
        )

        # อ่าน Netmask
        mask = found.findtext(
            "ip:ipv4/ip:address/ip:netmask",
            namespaces=namespaces
        )

        # รองรับ Interface ที่ยังไม่มี IPv4
        ipv4 = None

        if ip and mask:
            prefix = IPv4Network(
                f"0.0.0.0/{mask}"
            ).prefixlen

            ipv4 = f"{ip}/{prefix}"

        # หาก enabled ไม่ระบุ ให้ใช้ค่า Default เป็น up
        admin_state = (
            "down"
            if enabled is not None
            and enabled.strip().lower() == "false"
            else "up"
        )

        # คืนข้อมูลมาตรฐาน
        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": name,
                "ipv4": ipv4,
                "description": description,
                "admin_state": admin_state
            }
        }

    except Exception as exc:
        return backend_error(exc)


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""

    # อ่านสถานะปัจจุบันจาก Router
    response = get_interface_state(
        router,
        desired_interface["name"],
        netconf_get_config=netconf_get_config
    )

    # ถ้า Backend มี Error ให้ส่งกลับทันที
    if response["status"] == "error":
        return response

    # ถ้า Interface ไม่มีอยู่ จะเป็น None
    current_interface = response["interface"]

    # เรียก Planner จาก Part 2
    return build_plan(
        desired_interface,
        current_interface
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""

    try:
        # แยกหมายเลข Loopback
        name = desired_interface["name"]
        number = name.replace("Loopback", "", 1)

        # แปลง IPv4/CIDR
        ipv4 = IPv4Interface(
            desired_interface["ipv4"]
        )

        ip = str(ipv4.ip)
        mask = str(ipv4.network.netmask)

        # สร้าง NETCONF Config XML
        config = ET.Element(
            f"{{{NETCONF}}}config"
        )

        native = ET.SubElement(
            config,
            f"{{{NATIVE}}}native"
        )

        interface = ET.SubElement(
            native,
            f"{{{NATIVE}}}interface"
        )

        loopback = ET.SubElement(
            interface,
            f"{{{NATIVE}}}Loopback"
        )

        # Replace เพื่อให้ค่าตรง Desired State
        loopback.set(
            f"{{{NETCONF}}}operation",
            "replace"
        )

        # หมายเลข Loopback
        ET.SubElement(
            loopback,
            f"{{{NATIVE}}}name"
        ).text = number

        # Description
        ET.SubElement(
            loopback,
            f"{{{NATIVE}}}description"
        ).text = desired_interface["description"]

        # ตั้งค่า IPv4
        ip_element = ET.SubElement(
            loopback,
            f"{{{NATIVE}}}ip"
        )

        address = ET.SubElement(
            ip_element,
            f"{{{NATIVE}}}address"
        )

        primary = ET.SubElement(
            address,
            f"{{{NATIVE}}}primary"
        )

        ET.SubElement(
            primary,
            f"{{{NATIVE}}}address"
        ).text = ip

        ET.SubElement(
            primary,
            f"{{{NATIVE}}}mask"
        ).text = mask

        # down = shutdown / up = no shutdown
        if desired_interface["admin_state"] == "down":
            ET.SubElement(
                loopback,
                f"{{{NATIVE}}}shutdown"
            )

        config_xml = ET.tostring(
            config,
            encoding="unicode"
        )

        # ใช้ Fake Function สำหรับ Tests
        if netconf_edit_config is not None:
            netconf_edit_config(
                router,
                config_xml
            )

        else:
            # ส่ง edit-config ไป Router จริง
            with connect_router(router) as connection:
                reply = connection.edit_config(
                    target="running",
                    config=config_xml
                )

                if not reply.ok:
                    raise RuntimeError(
                        "NETCONF edit-config failed"
                    )

        return {
            "status": "ok",
            "result": "applied"
        }

    except Exception as exc:
        return backend_error(exc)
