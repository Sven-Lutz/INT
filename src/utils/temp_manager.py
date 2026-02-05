import threading

class TempManager:
    _instance = None
    _lock = threading.Lock()  # for thread safety

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self.temp_data = {}
        # You could also open/create your temp file here

    def set(self, key, value):
        self.temp_data[key] = value
        # optionally save to temp file here

    def get(self, key):
        return self.temp_data.get(key)

    # Add methods for file reading/writing as needed
