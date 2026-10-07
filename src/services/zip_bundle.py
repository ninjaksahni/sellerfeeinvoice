import io
import zipfile
from dataclasses import dataclass


@dataclass(frozen=True)
class ZipEntry:
    filename: str
    data: bytes


def build_zip_bytes(entries: list[ZipEntry]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            zf.writestr(entry.filename, entry.data)
    return buffer.getvalue()
