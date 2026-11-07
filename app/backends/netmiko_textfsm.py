
import os
from ipaddress import IPv4Address


# แปลงชื่อ Interface แบบย่อ เช่น Lo123 -> Loopback123
def normalize_name(name):
    name = str(name).strip()
    if name.lower().startswith("loopback"):
        return "Loopback" + name[8:]
    if name.lower().startswith("lo") and name[2:].isdigit():
        return "Loopback" + name[2:]
    return name


# แปลงข้อผิดพลาดจาก Netmiko เป็น Error ตาม Spec
def backend_error(exc):
    name = type(exc).__name__.lower()

    if isinstance(exc, PermissionError) or "authentication" in name:
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


# สร้างการเชื่อมต่อ SSH กับ Router
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


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""

    try:
        if netmiko_get is not None:
            # ใช้ข้อมูลจำลองจาก Public Tests
            ip_info, descriptions = netmiko_get(
                router, interface_name
            )
        else:
            # เชื่อม Router จริงผ่าน SSH
            connection = connect_router(router)

            try:
                # อ่าน IP, Prefix และสถานะ Interface
                ip_info = connection.send_command(
                    f"show ip interface {interface_name}",
                    use_textfsm=True
                )

                # อ่าน Description
                descriptions = connection.send_command(
                    "show interfaces description",
                    use_textfsm=True
                )
            finally:
                connection.disconnect()

        # TextFSM ต้องแปลงข้อมูลเป็น list ของ dictionary
        if not isinstance(ip_info, list):
            raise ValueError("Invalid TextFSM IP result")

        if not isinstance(descriptions, list):
            raise ValueError("Invalid TextFSM description result")

        # ค้นหา Interface ที่ต้องการ
        target = normalize_name(interface_name)
        found = None

        for item in ip_info:
            if normalize_name(item.get("interface", "")) == target:
                found = item
                break

        # ไม่พบ Interface
        if found is None:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        # อ่าน IP Address และ Prefix Length
        ip = found.get("ip_address", "")
        prefix = found.get("prefix_length", "")

        # TextFSM บาง Template คืนค่าเป็น list
        if isinstance(ip, list):
            ip = ip[0] if ip else ""

        if isinstance(prefix, list):
            prefix = prefix[0] if prefix else ""

        if not ip or not prefix:
            raise ValueError("Missing IPv4 address or prefix")

        ip = str(IPv4Address(ip))
        prefix = int(prefix)

        if not 0 <= prefix <= 32:
            raise ValueError("Invalid prefix")

        # หา Description โดยรองรับชื่อย่อ Lo123
        description = None

        for item in descriptions:
            name = item.get(
                "interface",
                item.get("port", "")
            )

            if normalize_name(name) == target:
                description = item.get("description") or None
                break

        # อ่าน Administrative State
        link_status = str(
            found.get(
                "link_status",
                found.get("status", "")
            )
        ).lower()

        admin_state = (
            "down"
            if "administratively down" in link_status
            else "up"
        )

        return {
            "status": "ok",
            "result": "found",
            "interface": {
                "name": target,
                "ipv4": f"{ip}/{prefix}",
                "description": description,
                "admin_state": admin_state
            }
        }

    except Exception as exc:
        return backend_error(exc)


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""

    try:
        # สำหรับ Public Tests ใช้ Fake Delete Function
        if netmiko_delete is not None:
            result = netmiko_delete(router, interface_name)

        else:
            # ตรวจสถานะก่อนลบ
            before = get_interface_state(router, interface_name)

            if before["status"] == "error":
                return before

            if before["result"] == "not_found":
                return {
                    "status": "ok",
                    "result": "not_found",
                    "interface": None
                }

            # เชื่อม Router จริง
            connection = connect_router(router)

            try:
                # ส่งคำสั่งลบ Loopback
                output = connection.send_config_set(
                    [f"no interface {interface_name}"]
                )

                # ตรวจว่าคำสั่งถูกปฏิเสธหรือไม่
                if any(word in output.lower() for word in (
                    "% invalid",
                    "% error",
                    "% incomplete",
                    "% ambiguous"
                )):
                    raise RuntimeError("Delete command failed")
            finally:
                connection.disconnect()

            # ตรวจสถานะหลังลบ
            after = get_interface_state(router, interface_name)

            if after["status"] == "error":
                return after

            if after["result"] != "not_found":
                raise RuntimeError("Interface still exists")

            result = "deleted"

        # ลบสำเร็จ
        if result == "deleted":
            return {"status": "ok", "result": "deleted"}

        # Interface ไม่มีอยู่แล้ว
        if result == "not_found":
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None
            }

        return {"status": "error", "result": "backend_failed"}

    except Exception as exc:
        return backend_error(exc)
