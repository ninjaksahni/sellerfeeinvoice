from src.services.zip_bundle import ZipEntry, build_zip_bytes
import zipfile
import io


def test_build_zip_bytes() -> None:
    data = build_zip_bytes(
        [
            ZipEntry("a.pdf", b"%PDF-1"),
            ZipEntry("b.pdf", b"%PDF-2"),
        ]
    )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(zf.namelist())
        assert names == ["a.pdf", "b.pdf"]
        assert zf.read("a.pdf") == b"%PDF-1"
