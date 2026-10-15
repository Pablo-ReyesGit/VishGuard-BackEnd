"""T9 - Rate limit de /login y límite de conexiones WS por usuario (en memoria; Redis en Sprint 3)."""
import time
from collections import defaultdict, deque
from contextlib import contextmanager


class TooManyConnections(Exception):
    pass


def client_key(headers: dict, peer_ip: str, trust_forwarded: bool = False) -> str:
    """Clave de rate limit. Detrás de ngrok/proxy el peer es siempre el proxy: activar
    trust_forwarded SOLO si el proxy es de confianza (si no, X-Forwarded-For es falsificable)."""
    if trust_forwarded:
        xff = headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return peer_ip


class SlidingWindowLimiter:
    def __init__(self, max_events: int = 5, window_seconds: float = 60.0,
                 max_keys: int = 10_000, gc_every: int = 500):
        self.max, self.window = max_events, window_seconds
        self.max_keys, self.gc_every = max_keys, gc_every
        self._hits: dict[str, deque] = {}
        self._calls = 0

    def _gc(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window]:
            del self._hits[k]
        while len(self._hits) > self.max_keys:       # tope duro: descarta la clave más antigua
            del self._hits[next(iter(self._hits))]

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._calls += 1
        if self._calls % self.gc_every == 0 or len(self._hits) > self.max_keys:
            self._gc(now)
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max:
            return False
        q.append(now)
        return True


class ConnectionLimiter:
    def __init__(self, max_per_user: int = 2):
        self.max = max_per_user
        self._active: dict[str, int] = {}

    def acquire(self, user_id: str) -> bool:
        n = self._active.get(user_id, 0)
        if n >= self.max:
            return False
        self._active[user_id] = n + 1
        return True

    def release(self, user_id: str) -> None:
        n = self._active.get(user_id, 0) - 1
        if n > 0:
            self._active[user_id] = n
        else:
            self._active.pop(user_id, None)   # no acumula claves en 0

    @contextmanager
    def hold(self, user_id: str):
        """with limiter.hold(uid): ...  -> libera siempre, aun con excepciones."""
        if not self.acquire(user_id):
            raise TooManyConnections(user_id)
        try:
            yield
        finally:
            self.release(user_id)
