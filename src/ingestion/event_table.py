import pandas as pd

from src.ingestion.closure_detection import detect_head_closures
from src.ingestion.event_assembly import assemble_event

EVENT_COLUMNS = [
    "ts",
    "machine_id",
    "head_id",
    "torque",
    "status",
    "error_class",
    "reject_signal",
    "cap_present",
]


def detect_head_ids(df):
    head_ids = []

    for column in df.columns:
        if column.endswith(" Count"):
            head_id = column.replace(" Count", "")
            head_ids.append(head_id)

    return sorted(head_ids)


def build_event_table(df, machine_id):
    events = []

    head_ids = detect_head_ids(df)

    for head_id in head_ids:

        closures = detect_head_closures(
            df,
            head_id,
        )

        for closure in closures:

            event = assemble_event(
                closure,
                machine_id,
            )

            events.append(event)

    event_table = pd.DataFrame(
    events,
    columns=EVENT_COLUMNS,
    )

    if event_table.empty:
        return event_table

    event_table = event_table.sort_values(
    by=["ts", "head_id"],
    kind="stable",
    ).reset_index(drop=True)

    return event_table