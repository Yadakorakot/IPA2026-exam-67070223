
import os
import json
import subprocess
import tempfile
from pathlib import Path
from ipaddress import IPv4Interface


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""

    try:
        # แปลง IPv4/CIDR เป็น IP และ Netmask
        ipv4 = IPv4Interface(desired_interface["ipv4"])

        # เตรียมตัวแปรที่ Ansible ต้องใช้
        variables = {
            "router": router,
            "interface_name": desired_interface["name"],
            "ipv4_address": str(ipv4.ip),
            "netmask": str(ipv4.network.netmask),
            "description": desired_interface["description"],
            "shutdown": desired_interface["admin_state"] == "down"
        }

        if run_playbook is not None:
            # ใช้ Fake Runner สำหรับ Public Tests
            run_playbook(variables)

        else:
            # เรียก Ansible จริง
            playbook = (
                Path(__file__).resolve().parents[2]
                / "ansible"
                / "apply_interface.yml"
            )

            # สร้าง Inventory ชั่วคราวสำหรับ Router เป้าหมาย
            with tempfile.TemporaryDirectory() as temp_dir:
                inventory = Path(temp_dir) / "inventory.ini"
                inventory.write_text(
                    f"[routers]\ntarget ansible_host={router}\n",
                    encoding="utf-8"
                )

                result = subprocess.run(
                    [
                        "ansible-playbook",
                        "-i", str(inventory),
                        str(playbook),
                        "--extra-vars", json.dumps(variables)
                    ],
                    capture_output=True,
                    text=True,
                    timeout=90
                )

            # ตรวจผลจาก Ansible
            if result.returncode != 0:
                output = (result.stdout + result.stderr).lower()

                if any(word in output for word in (
                    "authentication failed",
                    "permission denied",
                    "invalid password",
                    "authentication failure"
                )):
                    raise PermissionError("Ansible authentication failed")

                if any(word in output for word in (
                    "unreachable",
                    "connection refused",
                    "timed out",
                    "no route to host",
                    "could not resolve"
                )):
                    raise ConnectionError("Ansible connection failed")

                raise RuntimeError("Ansible playbook failed")

        # สำเร็จ
        return {"status": "ok", "result": "applied"}

    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}

    except (ConnectionError, TimeoutError, subprocess.TimeoutExpired):
        return {"status": "error", "result": "connection_failed"}

    except Exception:
        return {"status": "error", "result": "backend_failed"}
