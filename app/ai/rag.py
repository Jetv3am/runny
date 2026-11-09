"""Retrieval-Augmented Generation (RAG) for context-aware coaching.

Embeds the athlete's training history into a ChromaDB vector store so
the LLM can retrieve and reference specific past workouts when answering
coaching questions. This grounds responses in real data rather than
generic advice.

Architecture:
    1. Each run is transformed into a natural-language document with structured
       metadata (pace, HR, TRIMP, distance, date).
    2. Documents are embedded using ChromaDB's default embedding function
       (all-MiniLM-L6-v2 via sentence-transformers) and stored locally.
    3. On each coaching query, the top-K most relevant past runs are retrieved
       and injected into the Gemini prompt as grounded context.

References:
    Lewis, P. et al. (2020). Retrieval-Augmented Generation for
    Knowledge-Intensive NLP Tasks.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False

# Persistent vector store directory
VECTOR_STORE_DIR = Path("vector_store")
COLLECTION_NAME = "training_history"

# Singleton client
_client: Any = None
_collection: Any = None


def _format_pace_str(seconds_per_km: float) -> str:
    """Format pace as M:SS /km."""
    total = int(round(seconds_per_km))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}/km"


def _activity_to_document(activity: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Convert an activity to a natural-language document with metadata.

    Returns:
        (document_text, metadata_dict) or None if the activity is unusable.
    """
    if str(activity.get("type") or "").lower() != "running":
        return None

    distance_m = activity.get("distance_m")
    duration_s = activity.get("duration_s")
    if not isinstance(distance_m, (int, float)) or not isinstance(duration_s, (int, float)):
        return None
    if float(distance_m) < 500 or float(duration_s) < 60:
        return None

    distance_km = float(distance_m) / 1000.0
    pace_per_km = float(duration_s) / distance_km
    duration_min = float(duration_s) / 60.0

    # Parse date
    start_str = activity.get("start_date", "")
    try:
        dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
        date_str = dt.strftime("%A, %B %d, %Y")
        date_iso = dt.date().isoformat()
    except (ValueError, TypeError):
        date_str = str(start_str)[:10]
        date_iso = date_str

    # Heart rate info
    avg_hr = activity.get("average_heartrate")
    hr_str = f"Average HR: {int(float(avg_hr))} bpm" if isinstance(avg_hr, (int, float)) and float(avg_hr) > 0 else "No HR data"

    max_hr_val = activity.get("max_heartrate")
    max_hr_str = f", Max HR: {int(float(max_hr_val))} bpm" if isinstance(max_hr_val, (int, float)) and float(max_hr_val) > 0 else ""

    # Classify effort
    if isinstance(avg_hr, (int, float)) and float(avg_hr) > 0:
        hr_val = float(avg_hr)
        if hr_val > 170:
            effort = "very hard (race/interval effort)"
        elif hr_val > 155:
            effort = "hard (tempo/threshold effort)"
        elif hr_val > 140:
            effort = "moderate (steady-state effort)"
        else:
            effort = "easy (conversational effort)"
    else:
        if pace_per_km < 300:
            effort = "hard (fast pace)"
        elif pace_per_km < 360:
            effort = "moderate (steady pace)"
        else:
            effort = "easy (relaxed pace)"

    # Build natural-language document
    doc = (
        f"Running workout on {date_str}: "
        f"{distance_km:.1f} km in {duration_min:.0f} minutes at {_format_pace_str(pace_per_km)} pace. "
        f"{hr_str}{max_hr_str}. "
        f"Effort level: {effort}. "
        f"Source: {activity.get('source_name', activity.get('source', 'unknown'))}."
    )

    # Metadata for filtering
    metadata = {
        "date": date_iso,
        "distance_km": round(distance_km, 2),
        "duration_min": round(duration_min, 1),
        "pace_sec_per_km": round(pace_per_km, 1),
        "avg_hr": float(avg_hr) if isinstance(avg_hr, (int, float)) and float(avg_hr) > 0 else 0.0,
        "effort": effort.split("(")[0].strip(),
        "source": str(activity.get("source", "unknown")),
    }

    return doc, metadata


def _get_collection():
    """Get or create the ChromaDB collection (singleton)."""
    global _client, _collection

    if not _HAS_CHROMADB:
        return None

    if _collection is not None:
        return _collection

    try:
        VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(VECTOR_STORE_DIR),
        )
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        return _collection
    except Exception as exc:
        logger.error("Failed to initialize ChromaDB: %s", exc)
        return None


def index_training_history(
    activities: list[dict[str, Any]],
    force_reindex: bool = False,
) -> dict[str, Any]:
    """Index all running activities into the vector store.

    Skips activities that are already indexed (by stable ID hash).
    Set force_reindex=True to rebuild the entire store.

    Args:
        activities: Activity dicts from the database.
        force_reindex: If True, delete existing data and reindex everything.

    Returns:
        Summary of indexing operation.
    """
    collection = _get_collection()
    if collection is None:
        return {
            "status": "unavailable",
            "message": "ChromaDB is not installed. Run: pip install chromadb",
        }

    if force_reindex:
        # Clear existing data
        try:
            existing = collection.count()
            if existing > 0:
                all_ids = collection.get()["ids"]
                if all_ids:
                    collection.delete(ids=all_ids)
        except Exception:
            pass

    # Get existing IDs to skip duplicates
    try:
        existing_ids = set(collection.get()["ids"])
    except Exception:
        existing_ids = set()

    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []
    skipped = 0

    for activity in activities:
        # Generate stable ID from activity ID
        act_id = str(activity.get("id", ""))
        if not act_id:
            continue
        doc_id = hashlib.sha256(act_id.encode()).hexdigest()[:16]

        if doc_id in existing_ids:
            skipped += 1
            continue

        result = _activity_to_document(activity)
        if result is None:
            continue

        doc, meta = result
        documents.append(doc)
        metadatas.append(meta)
        ids.append(doc_id)

    indexed = 0
    if documents:
        # ChromaDB batches: max 5461 per add
        batch_size = 500
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i:i + batch_size]
            batch_metas = metadatas[i:i + batch_size]
            batch_ids = ids[i:i + batch_size]
            try:
                collection.add(
                    documents=batch_docs,
                    metadatas=batch_metas,
                    ids=batch_ids,
                )
                indexed += len(batch_docs)
            except Exception as exc:
                logger.error("Failed to index batch %d: %s", i // batch_size, exc)

    return {
        "status": "indexed",
        "documents_indexed": indexed,
        "documents_skipped": skipped,
        "total_in_store": collection.count(),
    }


def retrieve_relevant_runs(
    query: str,
    n_results: int = 5,
    effort_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve the most relevant past runs for a coaching query.

    Uses semantic similarity search over the embedded training history.

    Args:
        query: The runner's coaching question or context.
        n_results: Number of results to retrieve.
        effort_filter: Optional filter by effort level ('easy', 'moderate', 'hard').

    Returns:
        List of dicts with 'document', 'metadata', and 'distance' (similarity score).
    """
    collection = _get_collection()
    if collection is None or collection.count() == 0:
        return []

    where_filter = None
    if effort_filter:
        where_filter = {"effort": {"$eq": effort_filter}}

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            where=where_filter,
        )
    except Exception as exc:
        logger.error("Vector retrieval failed: %s", exc)
        return []

    retrieved = []
    if results and results.get("documents"):
        docs = results["documents"][0]
        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(docs)

        for doc, meta, dist in zip(docs, metas, distances):
            retrieved.append({
                "document": doc,
                "metadata": meta,
                "similarity_score": round(1.0 - dist, 4),  # Cosine: lower distance = more similar
            })

    return retrieved


def build_rag_context(
    query: str,
    n_results: int = 5,
) -> str:
    """Build a RAG context string to inject into an LLM prompt.

    Retrieves relevant past runs and formats them into a structured
    context block that can be prepended to the coaching prompt.

    Args:
        query: The runner's question.
        n_results: Number of relevant runs to include.

    Returns:
        Formatted context string, or empty string if no data available.
    """
    retrieved = retrieve_relevant_runs(query, n_results=n_results)
    if not retrieved:
        return ""

    lines = ["### Relevant Training History (retrieved from athlete's data):"]
    for i, run in enumerate(retrieved, 1):
        lines.append(f"\n**Run {i}** (relevance: {run['similarity_score']:.0%}):")
        lines.append(f"  {run['document']}")

    return "\n".join(lines)


def get_rag_status() -> dict[str, Any]:
    """Return the current status of the vector store."""
    collection = _get_collection()
    if collection is None:
        return {
            "status": "unavailable",
            "message": "ChromaDB is not installed or failed to initialize.",
            "total_documents": 0,
        }

    return {
        "status": "ready",
        "total_documents": collection.count(),
        "collection_name": COLLECTION_NAME,
        "store_path": str(VECTOR_STORE_DIR.absolute()),
    }
