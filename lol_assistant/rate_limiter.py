import time
from collections import deque


class RateLimiter:
    def __init__(self, max_calls, period_seconds):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.call_times = deque()  # timestamps of recent calls

    def wait_if_needed(self):
        now = time.time()

        # drop calls too old to count in the current window
        while self.call_times and now - self.call_times[0] > self.period_seconds:
            self.call_times.popleft()

        if len(self.call_times) >= self.max_calls:
            oldest_call = self.call_times[0]
            sleep_time = self.period_seconds - (now - oldest_call)
            if sleep_time > 0:
                time.sleep(sleep_time)

        self.call_times.append(time.time())
