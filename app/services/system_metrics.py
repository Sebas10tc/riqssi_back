from collections import deque
from threading import Lock


_response_times_ms: deque[float] = deque(maxlen=100)
_response_times_lock = Lock()


def record_response_time(duration_ms: float) -> None:
    with _response_times_lock:
        _response_times_ms.append(duration_ms)


def get_average_response_time() -> tuple[float, int]:
    with _response_times_lock:
        sample_count = len(_response_times_ms)
        average = sum(_response_times_ms) / sample_count if sample_count else 0.0
    return round(average, 2), sample_count
