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


class DriveFolderSource:
    """CSV files (or Google Sheets, exported as CSV) in the shared Google Drive folder."""

    label = "google_drive"

    def __init__(self, session, settings):
        from app.integrations import google

        self._google = google
        self._session = session
        self._settings = settings
        self._files: dict[str, google.DriveFile] | None = None

    def list_files(self) -> list[str]:
        files: dict = {}
        for f in self._google.list_folder(self._session, self._settings):
            name = f.name if f.name not in files else f"{f.name} ({f.id[:6]})"  # Drive allows duplicate names
            files[name] = f
        self._files = files
        return list(files)

    def read(self, name: str) -> SourceFile:
        if self._files is None:
            self.list_files()
        content, mime = self._google.download(self._session, self._settings, self._files[name])
        return SourceFile(name=name, mime_type=mime, content=content)


def fetch(source: ImportSource, batch_size: int) -> Iterator[list[SourceFile]]:
    """Yield the source's files in batches of `batch_size` until every file has been read."""
    names = source.list_files()
    for start in range(0, len(names), batch_size):
        yield [source.read(name) for name in names[start : start + batch_size]]
