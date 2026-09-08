STATUS_MAP = {
    0: ("Closure OK", False),
    2: ("No Load", False),
    3: ("No Load", True),
    4: ("No Closure", False),
    5: ("No Closure", True),
    8: ("No InTorque", False),
    9: ("No InTorque", True),
    16: ("No CapTurns", False),
    17: ("No CapTurns", True),
    32: ("Following Error", False),
    33: ("Following Error", True),
    64: ("Bad Closure", False),
    65: ("Bad Closure", True),
}


CAP_PRESENT_MAP = {
    0: True,
    2: False,
    65: True,
}


def decode_status(status):

    if status in STATUS_MAP:
        error_class, reject_signal = STATUS_MAP[status]

        return {
            "error_class": error_class,
            "reject_signal": reject_signal,
            "cap_present": CAP_PRESENT_MAP.get(status),
        }

    return {
        "error_class": f"Unknown ({status})",
        "reject_signal": None,
        "cap_present": None,
    }

def assemble_event(closure, machine_id):

    decoded = decode_status(closure["status"])

    return {
        "ts": closure["timestamp"],
        "machine_id": machine_id,
        "head_id": closure["head_id"],
        "torque": closure["torque"],
        "status": closure["status"],
        "error_class": decoded["error_class"],
        "reject_signal": decoded["reject_signal"],
        "cap_present": decoded["cap_present"],
    }