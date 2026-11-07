
import yaml


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    # TODO: implement

    # ตรวจว่า YAML เป็น dictionary หรือไม่
    if not isinstance(data, dict):
        return {"status": "error", "result": "invalid_yaml"}

    # ตรวจ version ต้องเป็นตัวเลข 1 เท่านั้น
    if type(data.get("version")) is not int or data["version"] != 1:
        return {"status": "error", "result": "invalid_version"}

    # ตรวจ router
    router = data.get("router")
    if not router:
        return {"status": "error", "result": "missing_router"}

    allowed_routers = [
        "10.0.29.101",
        "10.0.29.102",
        "10.0.29.103",
        "10.0.29.104",
        "10.0.29.105"
    ]

    if router not in allowed_routers:
        return {"status": "error", "result": "invalid_router"}

    # ตรวจ method
    method = data.get("method")
    if not method:
        return {"status": "error", "result": "missing_method"}

    allowed_methods = {
        "restconf": ["status", "plan", "apply"],
        "netconf": ["status", "plan", "apply"],
        "ansible": ["apply"],
        "netmiko-textfsm": ["status", "delete"]
    }

    if method not in allowed_methods:
        return {"status": "error", "result": "invalid_method"}

    # ตรวจ action
    action = data.get("action")
    if not action:
        return {"status": "error", "result": "missing_action"}

    if action not in allowed_methods[method]:
        return {"status": "error", "result": "invalid_action"}

    # ตรวจ desired
    desired = data.get("desired")
    if not isinstance(desired, dict):
        return {"status": "error", "result": "missing_desired"}

    # ตรวจ interface
    interface = desired.get("interface")
    if not isinstance(interface, dict):
        return {"status": "error", "result": "missing_interface"}

    # ตรวจชื่อ interface
    name = interface.get("name")
    if not isinstance(name, str) or not name.strip():
        return {"status": "error", "result": "missing_interface_name"}

    # plan และ apply ต้องมีข้อมูลครบ
    if action in ["plan", "apply"]:

        ipv4 = interface.get("ipv4")
        if not isinstance(ipv4, str) or not ipv4.strip():
            return {"status": "error", "result": "missing_ipv4"}

        description = interface.get("description")
        if not isinstance(description, str) or not description.strip():
            return {"status": "error", "result": "missing_description"}

        admin_state = interface.get("admin_state")
        if admin_state is None or admin_state == "":
            return {"status": "error", "result": "missing_admin_state"}

        if admin_state not in ["up", "down"]:
            return {"status": "error", "result": "invalid_admin_state"}

    # ข้อมูลถูกต้อง
    return {"status": "ok", "result": "accepted"}


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    # TODO: implement

    try:
        # เปิดและอ่าน YAML
        with open(path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError):
        return {"status": "error", "result": "invalid_yaml"}

    # ตรวจสอบข้อมูล
    return validate_request(data)
