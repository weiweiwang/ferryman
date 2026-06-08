import base64
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


SKILL_DIR = Path(__file__).resolve().parents[1]
BUILD_HTML = SKILL_DIR / "scripts" / "build_html_deck.py"
BUILD_HYBRID = SKILL_DIR / "scripts" / "build_hybrid_deck.py"
BUILD_HYBRID_PPTX = SKILL_DIR / "scripts" / "build_hybrid_pptx.py"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def require_node():
    if not shutil.which("node"):
        pytest.skip("Node.js is not available.")


def require_node_builder():
    require_node()
    probe = subprocess.run(
        ["node", "-e", "require.resolve('pptxgenjs')"],
        cwd=SKILL_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("pptxgenjs is not installed for the ppt-writer skill.")


def write_hybrid_spec(workspace: Path) -> Path:
    assets = workspace / "assets"
    assets.mkdir()
    (assets / "cover.png").write_bytes(PNG_1X1)
    spec = {
        "title": "Hybrid Test",
        "subtitle": "Fixture",
        "language": "zh-CN",
        "audience": "QA",
        "task_mode": "create",
        "primary_profile": "product-platform",
        "render_mode": "hybrid",
        "media_required": True,
        "theme": {
            "colors": {
                "bg": "071022",
                "ink": "FFFFFF",
                "muted": "CBD5E1",
                "accent": "D8AA35",
                "accent2": "53A3B8",
                "white": "FFFFFF",
            },
            "font": {"heading": "PingFang SC", "body": "PingFang SC"},
        },
        "slides": [
            {
                "number": 1,
                "type": "cover",
                "layout": "cover-photo",
                "layout_family": "cover-photo",
                "kicker": "QA",
                "claim": "Hybrid mode preserves visual composition and editable text.",
                "proof_object": "cover photo",
                "support": "Fixture image and native text overlay.",
                "image": {"path": "assets/cover.png", "fit": "cover", "source": "fixture"},
            }
        ],
    }
    spec_path = workspace / "deck-spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path


def test_build_html_deck_outputs_controlled_html_and_manifest(tmp_path):
    require_node()
    spec_path = write_hybrid_spec(tmp_path)
    html_dir = tmp_path / "html"
    manifest = html_dir / "deck-html-manifest.json"

    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_HTML),
            "--spec",
            str(spec_path),
            "--out-dir",
            str(html_dir),
            "--manifest",
            str(manifest),
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["slide_count"] == 1
    html = (html_dir / "slide-01.html").read_text(encoding="utf-8")
    assert "data-pptx=\"title\"" in html
    assert "Hybrid mode preserves" in html


def test_build_html_deck_supports_science_storybook_pattern_library(tmp_path):
    require_node()
    spec = {
        "title": "Earth Story",
        "language": "zh-CN",
        "visual_style": "science-storybook",
        "render_mode": "hybrid",
        "theme": {
            "template": "science-storybook",
            "colors": {"bg": "0C1620", "ink": "1C262B", "accent": "E08635", "accent2": "1E7185"},
            "font": {"heading": "PingFang SC", "body": "PingFang SC"},
        },
        "slides": [
            {
                "number": 1,
                "layout": "science-cover",
                "kicker": "Earth Story",
                "claim": "地球46亿年不是直线进步，而是一连串重启。",
                "support": "Science storybook fixture.",
                "items": [{"label": "撞击"}, {"label": "氧气"}, {"label": "灭绝"}],
            }
        ],
    }
    spec_path = tmp_path / "science-spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    html_dir = tmp_path / "html"
    manifest = html_dir / "deck-html-manifest.json"

    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_HTML),
            "--spec",
            str(spec_path),
            "--out-dir",
            str(html_dir),
            "--manifest",
            str(manifest),
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    html = (html_dir / "slide-01.html").read_text(encoding="utf-8")
    assert "science-bg-deep" in html
    assert "science-earth-orb" in html
    assert "data-pptx=\"title\"" in html
    assert "地球46亿年不是直线进步" in html


def test_build_hybrid_pptx_layers_editable_text_over_raster_background(tmp_path):
    require_node_builder()
    spec_path = write_hybrid_spec(tmp_path)
    preview = tmp_path / "preview-hybrid"
    preview.mkdir()
    background = preview / "slide-01.png"
    background.write_bytes(PNG_1X1)
    layout = {
        "slide_width_px": 1280,
        "slide_height_px": 720,
        "background_mode": "skeleton",
        "slides": [
            {
                "slide": 1,
                "background": str(background),
                "background_mode": "skeleton",
                "elements": [
                    {
                        "type": "title",
                        "tag": "div",
                        "text": "Editable Hybrid Title",
                        "rect": {"x": 80, "y": 90, "w": 760, "h": 90},
                        "style": {
                            "fontSize": "32px",
                            "fontFamily": "PingFang SC",
                            "fontWeight": "800",
                            "color": "rgb(255, 255, 255)",
                            "textAlign": "left",
                        },
                    }
                ],
            }
        ],
    }
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps(layout), encoding="utf-8")
    out = tmp_path / "output" / "hybrid.pptx"

    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_HYBRID_PPTX),
            "--spec",
            str(spec_path),
            "--layout",
            str(layout_path),
            "--out",
            str(out),
            "--editable-layer",
            "visible",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    with zipfile.ZipFile(out) as package:
        slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "Editable Hybrid Title" in slide_xml
    assert "FERRYMAN_HYBRID_BACKGROUND" in slide_xml


def test_build_hybrid_pptx_defaults_to_native_overlay(tmp_path):
    require_node_builder()
    spec_path = write_hybrid_spec(tmp_path)
    preview = tmp_path / "preview-hybrid"
    preview.mkdir()
    background = preview / "slide-01.png"
    background.write_bytes(PNG_1X1)
    layout = {
        "slide_width_px": 1280,
        "slide_height_px": 720,
        "background_mode": "skeleton",
        "slides": [
            {
                "slide": 1,
                "background": str(background),
                "background_mode": "skeleton",
                "elements": [
                    {
                        "type": "title",
                        "tag": "div",
                        "text": "Default Hybrid Overlay Title",
                        "rect": {"x": 80, "y": 90, "w": 760, "h": 90},
                        "style": {
                            "fontSize": "32px",
                            "fontFamily": "PingFang SC",
                            "fontWeight": "800",
                            "color": "rgb(255, 255, 255)",
                            "textAlign": "left",
                        },
                    }
                ],
            }
        ],
    }
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps(layout), encoding="utf-8")
    out = tmp_path / "output" / "default-hybrid.pptx"

    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_HYBRID_PPTX),
            "--spec",
            str(spec_path),
            "--layout",
            str(layout_path),
            "--out",
            str(out),
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    with zipfile.ZipFile(out) as package:
        slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "Default Hybrid Overlay Title" in slide_xml
    assert "FERRYMAN_HYBRID_BACKGROUND" in slide_xml


def test_build_hybrid_pptx_supports_explicit_visual_snapshot_without_native_overlay(tmp_path):
    require_node_builder()
    spec_path = write_hybrid_spec(tmp_path)
    preview = tmp_path / "preview-hybrid"
    preview.mkdir()
    background = preview / "slide-01.png"
    background.write_bytes(PNG_1X1)
    layout = {
        "slide_width_px": 1280,
        "slide_height_px": 720,
        "background_mode": "visual",
        "slides": [
            {
                "slide": 1,
                "background": str(background),
                "background_mode": "visual",
                "elements": [
                    {
                        "type": "title",
                        "tag": "div",
                        "text": "This text is already inside the rendered screenshot",
                        "rect": {"x": 80, "y": 90, "w": 760, "h": 90},
                        "style": {
                            "fontSize": "32px",
                            "fontFamily": "PingFang SC",
                            "fontWeight": "800",
                            "color": "rgb(255, 255, 255)",
                            "textAlign": "left",
                        },
                    },
                    {
                        "type": "image",
                        "tag": "img",
                        "text": "",
                        "rect": {"x": 640, "y": 0, "w": 640, "h": 720},
                        "style": {"objectFit": "cover"},
                    },
                ],
            }
        ],
    }
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps(layout), encoding="utf-8")
    out = tmp_path / "output" / "visual.pptx"

    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_HYBRID_PPTX),
            "--spec",
            str(spec_path),
            "--layout",
            str(layout_path),
            "--out",
            str(out),
            "--editable-layer",
            "none",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    with zipfile.ZipFile(out) as package:
        slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "This text is already inside" not in slide_xml
    assert "FERRYMAN_HYBRID_VISUAL_BACKGROUND" in slide_xml
    assert "content_images=1" in slide_xml


def test_build_hybrid_deck_rejects_visual_background_with_visible_overlay(tmp_path):
    require_node()
    spec_path = write_hybrid_spec(tmp_path)
    out = tmp_path / "output" / "bad-mode.pptx"

    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_HYBRID),
            "--spec",
            str(spec_path),
            "--out",
            str(out),
            "--background-mode",
            "visual",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Invalid hybrid mode pair" in result.stderr
