
def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    # TODO: implement

    # ข้อมูลที่ต้องเปรียบเทียบ
    fields = ["ipv4", "description", "admin_state"]

    # กรณีที่ 1: ยังไม่มี Interface ให้สร้างใหม่
    if current_interface is None:
        changes = {}

        for field in fields:
            changes[field] = {"to": desired_interface[field]}

        return {
            "status": "ok",
            "result": "planned",
            "operation": "create",
            "changes": changes
        }

    # กรณีที่ 2: มี Interface อยู่แล้ว
    changes = {}

    for field in fields:
        old_value = current_interface.get(field)
        new_value = desired_interface[field]

        # ถ้าค่าไม่ตรงกัน ให้เก็บค่าก่อนและหลัง
        if old_value != new_value:
            changes[field] = {
                "from": old_value,
                "to": new_value
            }

    # ถ้ามีค่าต่างกันให้ Update
    if changes:
        operation = "update"
    else:
        operation = "no_change"

    return {
        "status": "ok",
        "result": "planned",
        "operation": operation,
        "changes": changes
    }
