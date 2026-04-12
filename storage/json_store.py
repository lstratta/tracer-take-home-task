import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models.incident_record import IncidentRecord
from utils.logger import get_logger

log = get_logger("json_store")


class JsonStore:
    """Persists IncidentRecord objects as individual JSON files with an index.

    Directory layout mirrors Git's object store — files are placed in
    subdirectories named after the first two characters of their ID.
    This prevents any single directory from growing too large as the corpus
    scales:

        output/incidents/
          ab/
            ab3f7c2d.json
          cd/
            cd0012ff.json

    All writes are atomic: data is written to a temporary file first, then
    renamed to the final path. On all major operating systems, rename is
    atomic, so a partially-written file can never be read by a consumer.
    """

    def __init__(self, config: dict):
        storage = config.get("storage", {})
        self.output_directory = storage.get("output_directory", "./output/incidents")
        self.index_file = storage.get("index_file", "./output/index.json")
        self.run_state_file = storage.get("run_state_file", "./output/run_state.json")
        self.overwrite_existing = storage.get("overwrite_existing", False)

        os.makedirs(self.output_directory, exist_ok=True)
        index_dir = os.path.dirname(self.index_file)
        if index_dir:
            os.makedirs(index_dir, exist_ok=True)

    def _record_path(self, record_id: str) -> str:
        subdir = record_id[:2] if len(record_id) >= 2 else record_id
        return os.path.join(self.output_directory, subdir, f"{record_id}.json")

    def _atomic_write_json(self, path: str, data: Any) -> None:
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=dir_name or ".",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name
        os.replace(tmp_path, path)

    def load_index(self) -> Dict[str, Any]:
        """Load the index file, returning an empty structure if it does not exist."""
        if not os.path.exists(self.index_file):
            return {
                "last_updated": None,
                "total_records": 0,
                "source_sha": None,
                "records": [],
            }
        with open(self.index_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_index(self, index: Dict[str, Any]) -> None:
        self._atomic_write_json(self.index_file, index)

    def record_exists(self, record: IncidentRecord, index: Dict[str, Any]) -> bool:
        """Return True if any existing index entry matches by ID, URL, or content hash."""
        existing = index.get("records", [])
        ids = {r["id"] for r in existing}
        urls = {r.get("source_url") for r in existing if r.get("source_url")}
        hashes = {r.get("content_hash") for r in existing if r.get("content_hash")}
        return (
            record.id in ids
            or (record.source_url and record.source_url in urls)
            or record.content_hash in hashes
        )

    def save_record(
        self,
        record: IncidentRecord,
        index: Dict[str, Any],
        source_sha: Optional[str] = None,
    ) -> bool:
        """Write a record to disk and update the in-memory index.

        Args:
            record: The IncidentRecord to persist.
            index: Current index dict (mutated in place).
            source_sha: Source file SHA from the crawl.

        Returns:
            True if written, False if skipped due to overwrite_existing=false.
        """
        if not self.overwrite_existing and self.record_exists(record, index):
            log.debug("Record already exists — skipping", record_id=record.id)
            return False

        path = self._record_path(record.id)
        self._atomic_write_json(path, record.model_dump())

        entry = {
            "id": record.id,
            "title": record.title,
            "company": record.company,
            "section": record.section,
            "date": record.date,
            "quality_score": record.quality_score,
            "low_quality": record.low_quality,
            "potential_duplicate_of": record.potential_duplicate_of,
            "source_url": record.source_url,
            "content_hash": record.content_hash,
            "file_path": os.path.relpath(path, os.path.dirname(self.index_file) or "."),
        }

        existing_by_id = {r["id"]: i for i, r in enumerate(index["records"])}
        if record.id in existing_by_id:
            index["records"][existing_by_id[record.id]] = entry
        else:
            index["records"].append(entry)

        index["total_records"] = len(index["records"])
        index["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
        if source_sha:
            index["source_sha"] = source_sha

        return True

    def save_all(
        self,
        records: List[IncidentRecord],
        source_sha: Optional[str] = None,
    ) -> Dict[str, int]:
        """Persist all records and flush the index to disk.

        Args:
            records: Records to save.
            source_sha: Source file SHA from the crawl.

        Returns:
            Dict with 'saved' and 'skipped' counts.
        """
        index = self.load_index()
        saved = skipped = 0

        for record in records:
            try:
                if self.save_record(record, index, source_sha):
                    saved += 1
                else:
                    skipped += 1
            except Exception as exc:
                log.error("Failed to save record", record_id=record.id, error=str(exc))

        self._save_index(index)
        log.info("Storage complete", saved=saved, skipped=skipped, total=index["total_records"])
        return {"saved": saved, "skipped": skipped}

    def load_record(self, record_id: str) -> Optional[IncidentRecord]:
        """Load a single full IncidentRecord from its JSON file on disk.

        Used by the enrich command to read existing records before updating them.
        Returns None if the file doesn't exist or can't be deserialised.
        """
        path = self._record_path(record_id)
        if not os.path.exists(path):
            log.warning("Record file not found", record_id=record_id, path=path)
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return IncidentRecord(**data)
        except Exception as exc:
            log.error("Failed to load record", record_id=record_id, error=str(exc))
            return None

    def update_record(self, record: IncidentRecord, index: Dict[str, Any]) -> None:
        """Overwrite an existing record on disk and refresh its index entry.

        Used after enrichment — always writes regardless of overwrite_existing,
        since the caller has explicitly chosen to update a specific record.
        """
        path = self._record_path(record.id)
        # Write the full updated record to disk
        self._atomic_write_json(path, record.model_dump())

        # Refresh the index entry so quality_score, llm_enriched, and taxonomy stay in sync
        entry = {
            "id": record.id,
            "title": record.title,
            "company": record.company,
            "section": record.section,
            "date": record.date,
            "quality_score": record.quality_score,
            "low_quality": record.low_quality,
            "llm_enriched": record.llm_enriched,
            "potential_duplicate_of": record.potential_duplicate_of,
            "source_url": record.source_url,
            "content_hash": record.content_hash,
            "taxonomy_category": record.taxonomy_category,
            "taxonomy_subcategory": record.taxonomy_subcategory,
            "taxonomy_type": record.taxonomy_type,
            "file_path": os.path.relpath(path, os.path.dirname(self.index_file) or "."),
        }
        existing_by_id = {r["id"]: i for i, r in enumerate(index["records"])}
        if record.id in existing_by_id:
            index["records"][existing_by_id[record.id]] = entry
        else:
            # Shouldn't happen when enriching, but handle it safely
            index["records"].append(entry)

        index["total_records"] = len(index["records"])
        index["last_updated"] = datetime.now(tz=timezone.utc).isoformat()

    def load_run_state(self) -> Dict[str, Any]:
        """Load the run state file."""
        if not os.path.exists(self.run_state_file):
            return {}
        with open(self.run_state_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_run_state(self, state: Dict[str, Any]) -> None:
        """Persist the run state file atomically."""
        state_dir = os.path.dirname(self.run_state_file)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)
        self._atomic_write_json(self.run_state_file, state)
