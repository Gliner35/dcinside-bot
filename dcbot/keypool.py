import threading


class KeyPool:
    def __init__(self, keys):
        self._keys = [k.strip() for k in (keys or []) if k and k.strip()]
        self._idx = 0
        self._lock = threading.Lock()

    def __len__(self):
        with self._lock:
            return len(self._keys)

    @property
    def empty(self):
        with self._lock:
            return not self._keys

    def get(self):
        with self._lock:
            if not self._keys:
                return None
            key = self._keys[self._idx % len(self._keys)]
            self._idx += 1
            return key

    def peek(self):
        with self._lock:
            return self._keys[self._idx % len(self._keys)] if self._keys else None