"""Endpoints:

POST /api/prices/        enter one price             -> 201
POST /api/prices/bulk/   enter a JSON list, all-or-nothing -> 201 (or 400, nothing written)
GET  /api/prices/        list rows with provenance (origin, entered_by, reason)

Every write goes through crawlers.ingest.ingest_manual: the SAME validation and the SAME
idempotent upsert the scrapers use.
"""

from __future__ import annotations

import sqlalchemy as sa
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from crawlers import storage
from crawlers.ingest import ingest_manual
from manual_entry.db import get_engine
from manual_entry.serializers import PriceEntrySerializer, build_item


def _ingest(request, many: bool) -> Response:
    payload = request.data
    if many and not isinstance(payload, list):
        return Response({"detail": "expected a JSON list"}, status=status.HTTP_400_BAD_REQUEST)
    if not many and not isinstance(payload, dict):
        return Response({"detail": "expected a JSON object"}, status=status.HTTP_400_BAD_REQUEST)

    serializer = PriceEntrySerializer(data=payload, many=many)
    if not serializer.is_valid():
        return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    entered_by = request.user.username
    rows = serializer.validated_data if many else [serializer.validated_data]
    price_items = [build_item(row, entered_by) for row in rows]

    result = ingest_manual(get_engine(), price_items)
    if not result.ok:
        return Response({"errors": result.errors}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {"written": result.written, "entered_by": entered_by}, status=status.HTTP_201_CREATED
    )


class PriceCreateView(APIView):
    def post(self, request):
        return _ingest(request, many=False)

    def get(self, request):
        table = storage.iso_prices
        query = sa.select(table).order_by(table.c.interval_start_utc, table.c.node).limit(500)
        for param in ("source", "node", "origin"):
            if value := request.query_params.get(param):
                query = query.where(table.c[param] == value)
        with get_engine().connect() as conn:
            rows = [dict(row._mapping) for row in conn.execute(query)]
        for row in rows:
            row["interval_start_utc"] = row["interval_start_utc"].isoformat()
            row["price_usd_mwh"] = str(row["price_usd_mwh"])
            row["scraped_at"] = row["scraped_at"].isoformat()
        return Response({"count": len(rows), "results": rows})


class PriceBulkView(APIView):
    def post(self, request):
        return _ingest(request, many=True)
