
"""Apply interface configuration using Ansible."""

import json
import os
import subprocess
import tempfile

from pathlib import Path
from ipaddress import IPv4Interface


ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"


def apply_interface(router, desired_interface, run_playbook=None):
    """Apply complete desired interface state using Ansible."""

    try:
        ipv4 = IPv4Interface(desired_interface["ipv4"])

        variables = {
            "router": router,
            "interface_name": desired_interface["name"],
            "ipv4_address": str(ipv4.ip),
            "netmask": str(ipv4.network.netmask),
            "description": desired_interface["description"],
            "shutdown": desired_interface["admin_state"] == "down",
        }

        # ใช้ Fake Runner สำหรับ Public Tests
        if run_playbook is not None:
            run_playbook(variables)

        else:
            playbook = ANSIBLE_DIR / "apply_interface.yml"
            base_inventory = ANSIBLE_DIR / "inventory.ini"

            with tempfile.TemporaryDirectory() as temp_dir:
                inventory = Path(temp_dir) / "inventory.ini"

                inventory.write_text(
                    f"[routers]\ntarget ansible_host={router}\n",
                    encoding="utf-8"
                )

                env = {
                    **os.environ,
                    "ANSIBLE_HOST_KEY_CHECKING": "False",
                    "ANSIBLE_NOCOLOR": "1",
                }

                result = subprocess.run(
                    [
                        "ansible-playbook",
                        "-i", str(inventory),
                        "-i", str(base_inventory),
                        str(playbook),
                        "--extra-vars", json.dumps(variables),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    env=env,
                )

                if result.returncode != 0:
                    output = (
                        (result.stdout or "")
                        + (result.stderr or "")
                    ).lower()

                    if any(word in output for word in (
                        "authentication failed",
                        "authentication failure",
                        "permission denied",
                        "invalid password",
                    )):
                        raise PermissionError(
                            "Ansible authentication failed"
                        )

                    if any(word in output for word in (
                        "unreachable",
                        "connection refused",
                        "timed out",
                        "no route to host",
                        "could not resolve",
                        "connection failed",
                    )):
                        raise ConnectionError(
                            "Ansible connection failed"
                        )

                    raise RuntimeError(
                        "Ansible playbook failed"
                    )

        return {
            "status": "ok",
            "result": "applied"
        }

    except PermissionError:
        return {
            "status": "error",
            "result": "authentication_failed"
        }

    except (
        ConnectionError,
        TimeoutError,
        subprocess.TimeoutExpired
    ):
        return {
            "status": "error",
            "result": "connection_failed"
        }

    except Exception:
        return {
            "status": "error",
            "result": "backend_failed"
        }
