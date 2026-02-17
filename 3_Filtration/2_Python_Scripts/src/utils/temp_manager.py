import threading


class TempManager:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._data_lock = threading.Lock()
        self._temp_data: dict[str, object] = {}

    def set(self, key: str, value: object) -> None:
        with self._data_lock:
            self._temp_data[key] = value

    def get(self, key: str, default=None):
        with self._data_lock:
            return self._temp_data.get(key, default)

    def clear(self) -> None:
        with self._data_lock:
            self._temp_data.clear()

    def snapshot(self) -> dict:
        """Thread-safe copy of the current state."""
        with self._data_lock:
            return dict(self._temp_data)
