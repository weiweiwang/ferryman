import importlib.util
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "inspect_pptx.py"


def load_module():
    spec = importlib.util.spec_from_file_location("inspect_pptx", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_minimal_pptx(path: Path, *, slides: int = 2, empty_media: bool = False, url_text: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
""",
        )
        package.writestr(
            "ppt/presentation.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>
""",
        )
        for index in range(1, slides + 1):
            text = "Slide {index}".format(index=index)
            if url_text and index == 1:
                text = "Image source https://example.test/image.jpg"
            package.writestr(
                f"ppt/slides/slide{index}.xml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>
""",
            )
        package.writestr("ppt/media/image1.png", b"" if empty_media else b"fake image bytes")


def test_inspect_valid_minimal_pptx(tmp_path):
    module = load_module()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=2)

    report = module.inspect_pptx(pptx, expected_slides=2)

    assert report["ok"] is True
    assert report["metrics"]["slide_count"] == 2
    assert report["metrics"]["media_count"] == 1
    assert report["metrics"]["slide_text_chars"] > 0
    assert report["metrics"]["slides"][0]["text_chars"] > 0
    assert report["metrics"]["slides"][0]["shapes"] == 1


def test_inspect_reports_slide_count_mismatch(tmp_path):
    module = load_module()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=1)

    report = module.inspect_pptx(pptx, expected_slides=2)

    assert report["ok"] is False
    assert "Expected 2 slides, found 1." in report["errors"]


def test_inspect_reports_empty_media(tmp_path):
    module = load_module()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=1, empty_media=True)

    report = module.inspect_pptx(pptx, expected_slides=1)

    assert report["ok"] is False
    assert any("Empty media files" in error for error in report["errors"])


def test_inspect_reports_visible_urls_in_slide_text(tmp_path):
    module = load_module()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=1, url_text=True)

    report = module.inspect_pptx(pptx, expected_slides=1)

    assert report["ok"] is True
    assert report["metrics"]["naked_url_count"] == 1
    assert report["metrics"]["naked_url_slides"] == [1]
    assert report["metrics"]["slides"][0]["naked_urls"]
