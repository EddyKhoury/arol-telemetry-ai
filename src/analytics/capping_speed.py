def incremental_average(current_mean, new_value, n):
    return current_mean + (new_value - current_mean) / n

def closures_to_pieces_per_hour(closures, interval_seconds):

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    return closures * 3600 / interval_seconds

def running_capping_speed(closures_per_interval, interval_seconds):
    running_mean = 0.0
    running_speeds = []

    for n, closures in enumerate(closures_per_interval, start=1):
        speed = closures_to_pieces_per_hour(
            closures=closures,
            interval_seconds=interval_seconds,
        )

        running_mean = incremental_average(
            running_mean,
            speed,
            n,
        )

        running_speeds.append(running_mean)

    return running_speeds