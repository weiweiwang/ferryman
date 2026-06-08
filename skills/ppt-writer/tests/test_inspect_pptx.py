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


EMU = 914400


def write_minimal_pptx(
    path: Path,
    *,
    slides: int = 2,
    empty_media: bool = False,
    url_text: bool = False,
    picture_on_first_slide: bool = False,
    hybrid_background_on_first_slide: bool = False,
    visual_background_on_first_slide: bool = False,
) -> None:
    def picture_xml(
        index: int,
        *,
        x: float,
        y: float,
        w: float,
        h: float,
        descr: str = "",
    ) -> str:
        return f"""
  <p:pic>
    <p:nvPicPr>
      <p:cNvPr id="{index}" name="Picture {index}" descr="{descr}"/>
    </p:nvPicPr>
    <p:spPr>
      <a:xfrm>
        <a:off x="{int(x * EMU)}" y="{int(y * EMU)}"/>
        <a:ext cx="{int(w * EMU)}" cy="{int(h * EMU)}"/>
      </a:xfrm>
    </p:spPr>
  </p:pic>"""

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
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldSz cx="12192000" cy="6858000"/>
</p:presentation>
""",
        )
        for index in range(1, slides + 1):
            text = "Slide {index}".format(index=index)
            if url_text and index == 1:
                text = "Image source https://example.test/image.jpg"
            picture_xml_parts = []
            if hybrid_background_on_first_slide and index == 1:
                picture_xml_parts.append(
                    picture_xml(
                        10,
                        x=0,
                        y=0,
                        w=13.333,
                        h=7.5,
                        descr="FERRYMAN_HYBRID_BACKGROUND",
                    )
                )
            if visual_background_on_first_slide and index == 1:
                picture_xml_parts.append(
                    picture_xml(
                        12,
                        x=0,
                        y=0,
                        w=13.333,
                        h=7.5,
                        descr="FERRYMAN_HYBRID_VISUAL_BACKGROUND;content_images=1;content_image_area=0.4609;max_content_image_area=0.4609",
                    )
                )
            if picture_on_first_slide and index == 1:
                picture_xml_parts.append(picture_xml(11, x=1, y=1, w=4, h=2))
            picture_xml_text = "".join(picture_xml_parts)
            package.writestr(
                f"ppt/slides/slide{index}.xml",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>{picture_xml_text}</p:spTree></p:cSld>
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


def test_inspect_reports_picture_boxes_and_area(tmp_path):
    module = load_module()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=1, picture_on_first_slide=True)

    report = module.inspect_pptx(pptx, expected_slides=1)

    slide = report["metrics"]["slides"][0]
    assert slide["pictures"] == 1
    assert slide["picture_boxes"][0]["x"] == 1
    assert slide["picture_boxes"][0]["w"] == 4
    assert slide["max_picture_area_ratio"] > 0.07
    assert report["metrics"]["slide_width_inches"] > 13


def test_inspect_separates_hybrid_background_from_content_pictures(tmp_path):
    module = load_module()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(
        pptx,
        slides=1,
        picture_on_first_slide=True,
        hybrid_background_on_first_slide=True,
    )

    report = module.inspect_pptx(pptx, expected_slides=1)

    slide = report["metrics"]["slides"][0]
    assert slide["pictures"] == 2
    assert slide["content_pictures"] == 1
    assert slide["hybrid_background_pictures"] == 1
    assert slide["content_picture_area_ratio"] < slide["picture_area_ratio"]
    assert report["metrics"]["hybrid_background_count"] == 1


def test_inspect_extracts_visual_background_image_metadata(tmp_path):
    module = load_module()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=1, visual_background_on_first_slide=True)

    report = module.inspect_pptx(pptx, expected_slides=1)

    slide = report["metrics"]["slides"][0]
    assert slide["pictures"] == 1
    assert slide["content_pictures"] == 0
    assert slide["hybrid_background_pictures"] == 1
    assert slide["visual_content_images"] == 1
    assert slide["visual_max_content_image_area_ratio"] == 0.4609
    assert report["metrics"]["visual_content_image_count"] == 1


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
