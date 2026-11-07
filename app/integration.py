
"""Part 4 student implementation."""

import yaml

from app.core import validate_request
from app.dispatcher import dispatch_request
from app.request_handler import validate_webex_envelope


def process_request(mentioned_people, attachment_path, bot_person_id):
    # TODO: implement according to Part 4 specification

    # 1. ตรวจว่ามีการ Mention Bot และแนบ YAML
    result = validate_webex_envelope(
        mentioned_people,
        attachment_path,
        bot_person_id
    )

    # หากตรวจไม่ผ่าน ให้ส่ง Error กลับทันที
    if result is not None:
        return result

    # 2. อ่านไฟล์ YAML เพียงครั้งเดียว
    try:
        with open(attachment_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError):
        return {"status": "error", "result": "invalid_yaml"}

    # 3. ตรวจสอบเนื้อหา YAML โดยใช้ Part 1
    result = validate_request(data)

    # หาก YAML ไม่ถูกต้อง ไม่ส่งไปยัง Router
    if result["status"] == "error":
        return result

    # 4. หากผ่าน ให้ Dispatcher เลือก Backend
    return dispatch_request(data)
