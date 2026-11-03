"""Re-embeds every runbook and stored incident with the current embedding model.

Run after changing EMBEDDING_MODEL: vectors from different models are not comparable.
    python -m app.services.reindex
"""

import asyncio
import json

from app.services.qdrant_service import close_shared_qdrant_service, get_shared_qdrant_service

RUNBOOK_LIMIT = 1000


async def reindex_all() -> dict[str, int]:
    qdrant = get_shared_qdrant_service()
    try:
        runbooks = await qdrant.list_runbooks(limit=RUNBOOK_LIMIT)
        for runbook in runbooks:
            await qdrant.upsert_runbook(runbook)
        incidents = await qdrant.reembed_historical_incidents()
        return {"runbooks": len(runbooks), "incidents": incidents}
    finally:
        await close_shared_qdrant_service()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(reindex_all())))
