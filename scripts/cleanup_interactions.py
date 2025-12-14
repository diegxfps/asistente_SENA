"""Limpia interacciones antiguas para mantener bajo el almacenamiento."""
from datetime import datetime, timedelta
import os

from sqlalchemy import text

from app.db import engine


DEFAULT_RETENTION_DAYS = 180


def main() -> None:
    cutoff_days = int(os.getenv("RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
    cutoff_date = datetime.utcnow() - timedelta(days=cutoff_days)

    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM interactions WHERE created_at < :cutoff"),
            {"cutoff": cutoff_date},
        )
        deleted = result.rowcount or 0

    print(f"Eliminadas {deleted} interacciones anteriores a {cutoff_date.date()}")


if __name__ == "__main__":
    main()
