
import os
import xml.etree.ElementTree as ET
from ipaddress import IPv4Interface, IPv4Network
from app.planner import build_plan

IETF = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IETF_IP = "urn:ietf:params:xml:ns:yang:ietf-ip"
NATIVE = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"
NETCONF = "urn:ietf:params:xml:ns:netconf:base:1.0"


# แปลง Exception เป็น Error ตาม Spec
def backend_error(exc):
    name = type(exc).__name__

    if isinstance(exc, PermissionError) or "Authentication" in name:
        result = "authentication_failed"
    elif isinstance(exc, (ConnectionError, TimeoutError)) or name in (
        "SSHError", "SessionCloseError", "TransportError",
        "SocketError", "TimeoutError"
    ):
        result = "connection_failed"
    else:
        result = "backend_failed"

    return {"status": "error", "result": result}


# ติดต่อ Router ผ่าน NETCONF จริง
def connect_router(router):
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
        # สร้าง XML Filter สำหรับอ่าน Interface
        root = ET.Element(f"{{{IETF}}}interfaces")
        interface = ET.SubElement(root, f"{{{IETF}}}interface")
        ET.SubElement(interface, f"{{{IETF}}}name").text = interface_name

        filter_xml = ET.tostring(root, encoding="unicode")

        if netconf_get_config is not None:
            # ใช้ฟังก์ชันจำลองสำหรับ Tests
            xml_data = netconf_get_config(router, filter_xml)
        else:
            # อ่าน running configuration จาก Router จริง
            with connect_router(router) as connection:
                reply = connection.get_config(
                    source="running",
                    filter=("subtree", filter_xml)
                )
                xml_data = reply.data_xml

        # แปลง XML เป็น Element
        xml_root = ET.fromstring(xml_data)

        ns = {"if": IETF, "ip": IETF_IP}

        # ค้นหา Interface ที่ต้องการ
        found = None
        for item in xml_root.findall(".//if:interface", ns):
            if item.findtext("if:name", namespaces=ns) == interface_name:
                found = item
                break

        if found is None:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        # ดึงข้อมูล Interface
        name = found.findtext("if:name", namespaces=ns)
        description = found.findtext(
            "if:description", namespaces=ns
        )
        enabled = found.findtext("if:enabled", namespaces=ns)

        ip = found.findtext(
            "ip:ipv4/ip:address/ip:ip", namespaces=ns
        )
        mask = found.findtext(
            "ip:ipv4/ip:address/ip:netmask", namespaces=ns
        )

        # แปลง Netmask เป็น Prefix เช่น /32
        prefix = IPv4Network(f"0.0.0.0/{mask}").prefixlen

        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": name,
                "ipv4": f"{ip}/{prefix}",
                "description": description,
                "admin_state": (
                    "down" if enabled == "false" else "up"
                )
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

    # อ่านสถานะปัจจุบันจาก NETCONF
    response = get_interface_state(
        router,
        desired_interface["name"],
        netconf_get_config=netconf_get_config
    )

    # ถ้าอ่าน Router ไม่สำเร็จ ส่ง Error กลับ
    if response["status"] == "error":
        return response

    # ใช้ Planner ที่ทำไว้ใน Part 2
    return build_plan(
        desired_interface,
        response["interface"]
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""

    try:
        # แยกชื่อ Loopback และ IPv4
        number = desired_interface["name"].replace("Loopback", "", 1)
        ipv4 = IPv4Interface(desired_interface["ipv4"])

        ip = str(ipv4.ip)
        mask = str(ipv4.network.netmask)

        # สร้าง NETCONF XML
        config = ET.Element(f"{{{NETCONF}}}config")
        native = ET.SubElement(config, f"{{{NATIVE}}}native")
        interface = ET.SubElement(native, f"{{{NATIVE}}}interface")
        loopback = ET.SubElement(
            interface,
            f"{{{NATIVE}}}Loopback"
        )

        # ใช้ replace เพื่อแทนค่าทั้ง Interface
        loopback.set(f"{{{NETCONF}}}operation", "replace")

        ET.SubElement(
            loopback, f"{{{NATIVE}}}name"
        ).text = number

        ET.SubElement(
            loopback, f"{{{NATIVE}}}description"
        ).text = desired_interface["description"]

        ip_element = ET.SubElement(
            loopback, f"{{{NATIVE}}}ip"
        )
        address = ET.SubElement(
            ip_element, f"{{{NATIVE}}}address"
        )
        primary = ET.SubElement(
            address, f"{{{NATIVE}}}primary"
        )

        ET.SubElement(
            primary, f"{{{NATIVE}}}address"
        ).text = ip

        ET.SubElement(
            primary, f"{{{NATIVE}}}mask"
        ).text = mask

        # ถ้า admin_state เป็น down ให้ shutdown
        if desired_interface["admin_state"] == "down":
            ET.SubElement(loopback, f"{{{NATIVE}}}shutdown")

        config_xml = ET.tostring(config, encoding="unicode")

        if netconf_edit_config is not None:
            # ใช้ฟังก์ชันจำลองสำหรับ Tests
            netconf_edit_config(router, config_xml)
        else:
            # ส่ง edit-config ไป Router จริง
            with connect_router(router) as connection:
                reply = connection.edit_config(
                    target="running",
                    config=config_xml
                )
                if not reply.ok:
                    raise RuntimeError("NETCONF edit-config failed")

        return {"status": "ok", "result": "applied"}

    except Exception as exc:
        return backend_error(exc)
