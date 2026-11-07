
"""Part 4 student implementation."""

from app.backends import ansible, netconf, netmiko_textfsm, restconf


def dispatch_request(data):
    # TODO: implement according to Part 4 specification

    # ดึงข้อมูลจาก YAML ที่ตรวจสอบผ่าน Part 1 แล้ว
    router = data["router"]
    method = data["method"]
    action = data["action"]
    interface = data["desired"]["interface"]

    # เลือก Backend ตาม method
    backends = {
        "restconf": restconf,
        "netconf": netconf,
        "ansible": ansible,
        "netmiko-textfsm": netmiko_textfsm
    }

    backend = backends.get(method)

    if backend is None:
        return {"status": "error", "result": "invalid_method"}

    # ตรวจว่า method รองรับ action หรือไม่
    allowed_actions = {
        "restconf": ["status", "plan", "apply"],
        "netconf": ["status", "plan", "apply"],
        "ansible": ["apply"],
        "netmiko-textfsm": ["status", "delete"]
    }

    if action not in allowed_actions[method]:
        return {"status": "error", "result": "invalid_action"}

    # status ใช้ชื่อ Interface
    if action == "status":
        return backend.get_interface_state(
            router, interface["name"]
        )

    # plan ใช้ข้อมูล Interface ทั้งหมด
    if action == "plan":
        return backend.plan_interface(
            router, interface
        )

    # apply ใช้ข้อมูล Interface ทั้งหมด
    if action == "apply":
        return backend.apply_interface(
            router, interface
        )

    # delete ใช้ชื่อ Interface
    if action == "delete":
        return backend.delete_interface(
            router, interface["name"]
        )
