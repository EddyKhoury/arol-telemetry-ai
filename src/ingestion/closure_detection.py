def detect_head_closures(df, head_id):

    count_col = f"{head_id} Count"
    torque_col = f"{head_id} AppTorque"
    status_col = f"{head_id} Status"

    closures = []

    for i in range(1, len(df)):

        previous_row = df.iloc[i - 1]
        current_row = df.iloc[i]

        previous_count = previous_row[count_col]
        current_count = current_row[count_col]

        if current_count == previous_count + 1:

            closure = {
                "row_index": i,
                "head_id": head_id,
                "torque": current_row[torque_col],
                "status": current_row[status_col],
                "timestamp": current_row["timestamp"],
            }

            closures.append(closure)

    return closures