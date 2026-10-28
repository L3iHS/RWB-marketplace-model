"""Ограниченный кэш готовых ответов с одним вычислением при одновременных промахах."""
from collections import OrderedDict
from threading import Lock
from time import monotonic


_MISSING = object()


class DashboardCache:
    def __init__(self, max_entries=16, ttl_seconds=60, clock=monotonic):
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError('Размер и срок жизни кэша должны быть положительными')
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries = OrderedDict()
        self._entries_lock = Lock()
        self._compute_lock = Lock()

    def _get(self, key):
        with self._entries_lock:
            entry = self._entries.get(key)
            if entry is None:
                return _MISSING
            deadline, value = entry
            if self._clock() >= deadline:
                del self._entries[key]
                return _MISSING
            self._entries.move_to_end(key)
            return value

    def get_or_compute(self, key, compute):
        value = self._get(key)
        if value is not _MISSING:
            return value
        # Горячие ответы доступны и пока другой запрос строит новый срез.
        with self._compute_lock:
            value = self._get(key)
            if value is not _MISSING:
                return value
            value = compute()  # Исключение не попадает в кэш.
            with self._entries_lock:
                self._entries[key] = (self._clock() + self.ttl_seconds, value)
                self._entries.move_to_end(key)
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
            return value
