"""Async retry decorator with exponential backoff."""

from __future__ import annotations

import asyncio
import random
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Type


def async_retry(
    retries: int = 3,
    backoff: float = 1.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
) -> Callable[..., Any]:
    """Retry an async function with exponential backoff."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Optional[BaseException] = None
            for attempt in range(retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[misc]
                    last_error = exc
                    if attempt >= retries:
                        raise
                    sleep_for = backoff * (2 ** attempt) + random.uniform(0, 0.5)
                    await asyncio.sleep(sleep_for)
            if last_error is not None:
                raise last_error
            raise RuntimeError("Retry loop exited without a result.")

        return wrapper

    return decorator
