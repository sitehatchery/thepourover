"""Where import files come from. Each source yields files in batches so large drops don't load at once."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SourceFile:
    name: str
    mime_type: str
    content: bytes


class ImportSource(Protocol):
    label: str

    def list_files(self) -> list[str]: ...

    def read(self, name: str) -> SourceFile: ...


class LocalFolderSource:
    """CSV files in a folder on disk (the bundled sample data, or any drop folder)."""

    label = "local"

    def __init__(self, folder: Path):
        self.folder = folder

    def list_files(self) -> list[str]:
        if not self.folder.is_dir():
            raise FileNotFoundError(f"Import folder not found: {self.folder}")
        return sorted(p.name for p in self.folder.iterdir() if p.is_file() and not p.name.startswith("."))

    def read(self, name: str) -> SourceFile:
        path = self.folder / name
        mime = "text/csv" if path.suffix.lower() == ".csv" else "application/octet-stream"
        return SourceFile(name=name, mime_type=mime, content=path.read_bytes())


def fetch(source: ImportSource, batch_size: int) -> Iterator[list[SourceFile]]:
    """Yield the source's files in batches of `batch_size` until every file has been read."""
    names = source.list_files()
    for start in range(0, len(names), batch_size):
        yield [source.read(name) for name in names[start : start + batch_size]]
