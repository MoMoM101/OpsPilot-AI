from typing import Any

from fastapi import Response

PAGINATION_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "headers": {
            "X-Total-Count": {
                "description": "Total number of records matching the current filters.",
                "schema": {"type": "integer", "minimum": 0},
            },
            "X-Limit": {
                "description": "Page size applied to this response.",
                "schema": {"type": "integer", "minimum": 1},
            },
            "X-Offset": {
                "description": "Zero-based offset applied to this response.",
                "schema": {"type": "integer", "minimum": 0},
            },
        }
    }
}


def set_pagination_headers(
    response: Response, *, total: int, limit: int, offset: int
) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
