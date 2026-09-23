import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


class BatchProcessor:
    """Process a folder or watch directory with deduplication and bounded concurrency."""

    def __init__(self,
                 input_path: str,
                 max_workers: int = 4,
                 max_upload_workers: int = 2,
                 max_ffmpeg_workers: int = 2,
                 max_cpu_workers: int = 2,
                 max_gpu_workers: int = 2,
                 include_directories: bool = False):
        self.input_path = input_path
        self.max_workers = max(1, max_workers)
        self.max_upload_workers = max(1, max_upload_workers)
        self.max_ffmpeg_workers = max(1, max_ffmpeg_workers)
        self.max_cpu_workers = max(1, max_cpu_workers)
        self.max_gpu_workers = max(1, max_gpu_workers)
        self.include_directories = include_directories
        self._seen_hashes: set[str] = set()

    def _hash_file(self, file_path: str) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _iter_input_files(self) -> list[str]:
        path = Path(self.input_path)
        if path.is_file():
            return [str(path.resolve())]
        if not path.exists():
            return []

        files: list[str] = []
        for item in sorted(path.iterdir()):
            if item.is_file() and item.suffix.lower() in {
                    ".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"
            }:
                files.append(str(item.resolve()))
        return files

    def _process_single_item(self, file_path: str) -> dict[str, Any]:
        digest = self._hash_file(file_path)
        if digest in self._seen_hashes:
            return {"input": file_path, "status": "skipped", "reason": "duplicate-content"}
        self._seen_hashes.add(digest)
        return {"input": file_path, "status": "processed", "hash": digest}

    def _process_directory(self) -> dict[str, Any]:
        files = self._iter_input_files()
        report = {
            "total_items": len(files),
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "items": [],
        }

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self._process_single_item, item) for item in files]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - defensive path
                    logging.warning("Batch item failed: %s", exc)
                    report["failed"] += 1
                    continue

                if not isinstance(result, dict):
                    result = {"status": "failed", "reason": str(result)}

                report["items"].append(result)
                if result.get("status") == "processed":
                    report["processed"] += 1
                elif result.get("status") == "skipped":
                    report["skipped"] += 1
                elif result.get("status") == "failed":
                    report["failed"] += 1

        return report
