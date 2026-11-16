"""One SQLAlchemy engine per database URL, created lazily, tables ensured once."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from django.conf import settings

from crawlers import storage

_engines: dict[str, sa.Engine] = {}


def get_engine() -> sa.Engine:
    url = settings.MANUAL_ENTRY_DATABASE_URL
    if url not in _engines:
        parsed = sa.engine.make_url(url)
        if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        engine = sa.create_engine(url, pool_pre_ping=True)
        storage.create_all(engine)
        _engines[url] = engine
    return _engines[url]
