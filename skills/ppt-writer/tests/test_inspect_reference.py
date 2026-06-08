import importlib.util
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "inspect_reference.py"


def load_module():
    spec = importlib.util.spec_from_file_location("inspect_reference", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_reference_pptx(path: Path) -> None:
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
        package.writestr(
            "ppt/slides/slide1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp>
      <p:spPr><a:xfrm><a:off x="914400" y="914400"/><a:ext cx="5486400" cy="914400"/></a:xfrm></p:spPr>
      <p:txBody><a:p><a:r><a:rPr sz="3600"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:rPr><a:t>参考标题</a:t></a:r></a:p></p:txBody>
    </p:sp>
    <p:pic>
      <p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="12192000" cy="6858000"/></a:xfrm></p:spPr>
    </p:pic>
  </p:spTree></p:cSld>
</p:sld>
""",
        )
        package.writestr("ppt/media/image1.jpeg", b"fake image bytes")


def test_audit_reference_extracts_slide_rhythm(tmp_path):
    module = load_module()
    pptx = tmp_path / "reference.pptx"
    write_reference_pptx(pptx)

    report = module.audit_reference(pptx)

    assert report["ok"] is True
    assert report["summary"]["slide_count"] == 1
    assert report["summary"]["media_count"] == 1
    assert report["summary"]["image_slide_ratio"] == 1
    assert report["summary"]["pictures_per_slide"] == 1
    assert report["slides"][0]["layout_label"] == "image-led"
    assert report["slides"][0]["dominant_text"]["max_font_pt"] == 36
    assert report["recommended_constraints"]["min_image_slide_ratio"] >= 0.6
