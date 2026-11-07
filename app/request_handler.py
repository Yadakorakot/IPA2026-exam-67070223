
from app.core import process_request_file


def validate_webex_envelope(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the target bot's actual mention and YAML attachment.
    Return an error response, or None when the envelope is valid.
    """
    # TODO: implement according to the published specifications

    # ตรวจว่า bot_person_id ถูกต้องและถูก mention จริง
    if (
        not isinstance(bot_person_id, str)
        or not bot_person_id
        or not isinstance(mentioned_people, list)
        or bot_person_id not in mentioned_people
    ):
        return {"status": "error", "result": "missing_bot_mention"}

    # ตรวจว่ามีไฟล์ YAML แนบมาหรือไม่
    if attachment_path is None:
        return {"status": "error", "result": "no_yaml"}

    # ผ่านการตรวจสอบ
    return None


def handle_webex_request(
    mentioned_people,
    attachment_path,
    bot_person_id,
):
    """
    Validate the envelope, then validate the attached YAML request.
    Return a response dictionary. Do not dispatch to a router.
    """
    # TODO: implement according to the published specifications

    # ตรวจ mention และไฟล์แนบก่อน
    result = validate_webex_envelope(
        mentioned_people,
        attachment_path,
        bot_person_id,
    )

    # หากตรวจไม่ผ่าน ส่ง Error กลับทันที
    if result is not None:
        return result

    # หากผ่าน ให้อ่านและตรวจ YAML ด้วย core.py
    return process_request_file(attachment_path)
