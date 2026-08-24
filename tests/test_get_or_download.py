"""main.get_or_download: transient_local_copy avoids stray zips.

CUF/Protocol zips are deleted right after extraction, so the NEXT run that
still targets the same document finds no cached copy and re-downloads it
just to verify the hash. Once verified unchanged, that redundant copy must
not be left sitting on disk forever -- reproduces the bug where a CUF zip
kept reappearing next to its already-extracted folder."""
from datetime import datetime

from main import get_or_download
from src.browser.download_utils import sha256_file
from src.browser.spp_client import SppDocument
from src.state.metadata_store import MetadataStore


class _FakeClient:
    """Always downloads the same fixed content, mimicking a document whose
    source content hasn't changed between calls."""

    def __init__(self, content: bytes = b"same content every time"):
        self.content = content
        self.calls = 0

    def download(self, document, target_dir):
        self.calls += 1
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / document.filename
        path.write_bytes(self.content)
        return path


def _document(filename="CUF Meeting Materials 20260716.zip"):
    return SppDocument(
        document_id="77179",
        title="CUF Meeting Materials 20260716",
        filename=filename,
        url="https://www.spp.org/Documents/77179/" + filename,
        published_date=None,  # named_with_date() then reduces to the raw filename
    )


def test_transient_local_copy_deletes_redundant_reverification_download(tmp_path):
    state = MetadataStore(tmp_path / "state.json")
    client = _FakeClient()
    downloads_dir = tmp_path / "CUF"
    document = _document()

    # First run: brand new document -> downloaded and kept (extraction, not
    # modeled here, would consume and then delete it -- simulated below).
    path, is_new = get_or_download(
        family="cuf", document=document, client=client, state=state,
        downloads_dir=downloads_dir, dry_run=False, warnings=[],
        transient_local_copy=True,
    )
    assert is_new is True
    assert path is not None and path.exists()
    path.unlink()  # mimic main.py's "extract_pdfs then unlink the zip"

    # Second run: same document, unchanged content, but the cached copy is
    # gone (deleted above) -- forces a re-download purely to verify the hash.
    path2, is_new2 = get_or_download(
        family="cuf", document=document, client=client, state=state,
        downloads_dir=downloads_dir, dry_run=False, warnings=[],
        transient_local_copy=True,
    )
    assert is_new2 is False
    assert path2 is None
    assert client.calls == 2
    assert list(downloads_dir.iterdir()) == []  # no stray zip left behind


def test_without_transient_local_copy_keeps_the_reverified_file(tmp_path):
    # SUF/RR-Master behavior must be unchanged: their local copy is meant to
    # persist, so a re-verified-unchanged download is kept, not deleted.
    state = MetadataStore(tmp_path / "state.json")
    client = _FakeClient()
    downloads_dir = tmp_path / "SUF"
    document = _document("SUF Meeting Materials 20260409.pdf")

    path, _ = get_or_download(
        family="suf", document=document, client=client, state=state,
        downloads_dir=downloads_dir, dry_run=False, warnings=[],
    )
    path.unlink()  # simulate the file going missing some other way

    path2, is_new2 = get_or_download(
        family="suf", document=document, client=client, state=state,
        downloads_dir=downloads_dir, dry_run=False, warnings=[],
    )
    assert is_new2 is False
    assert path2 is not None and path2.exists()
