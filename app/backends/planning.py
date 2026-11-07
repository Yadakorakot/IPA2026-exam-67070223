
from app.planner import build_plan


def plan_interface(
    router,
    desired_interface,
    get_interface_state,
):
    """Build a Part 2 plan from backend status."""
    # อ่านสถานะ Interface จาก Backend
    response = get_interface_state(
        router,
        desired_interface["name"]
    )

    # ถ้า Backend ทำงานผิดพลาด ให้ส่ง Error กลับ
    if response["status"] == "error":
        return response

    # ถ้าไม่พบ Interface ค่า current จะเป็น None
    # ถ้าพบ Interface จะได้ข้อมูลปัจจุบัน
    current_interface = response["interface"]

    # เรียก Planner จาก Part 2 เพื่อวางแผน
    return build_plan(
        desired_interface,
        current_interface
    )
