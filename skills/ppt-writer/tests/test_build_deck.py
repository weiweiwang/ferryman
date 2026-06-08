import base64
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "build_deck.py"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def require_node_builder():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available.")
    probe = subprocess.run(
        [node, "-e", "require.resolve('pptxgenjs')"],
        cwd=SKILL_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("pptxgenjs is not installed for the ppt-writer skill.")


def write_image_grid_spec(workspace: Path) -> Path:
    assets = workspace / "assets"
    assets.mkdir()
    (assets / "one.png").write_bytes(PNG_1X1)
    (assets / "two.png").write_bytes(PNG_1X1)
    spec = {
        "title": "Theme Grid Test",
        "language": "en-US",
        "audience": "QA",
        "theme": {
            "colors": {
                "bg": "F5F2EA",
                "ink": "111111",
                "accent": "D9292E",
                "accent2": "1F4E8C",
            },
            "font": {"heading": "Aptos Display", "body": "Aptos"},
        },
        "task_mode": "create",
        "primary_profile": "product-platform",
        "slides": [
            {
                "number": 1,
                "type": "generic",
                "layout": "image-grid",
                "layout_family": "topic-grid",
                "claim": "Labels render on image grids.",
                "proof_object": "image grid",
                "support": "The builder should consume theme colors and image labels.",
                "items": ["First", "Second"],
                "images": [
                    {"path": "assets/one.png", "source": "fixture"},
                    {"path": "assets/two.png", "source": "fixture"},
                ],
            }
        ],
    }
    spec_path = workspace / "deck-spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path


def test_build_deck_supports_nested_theme_and_image_grid_labels(tmp_path):
    require_node_builder()
    spec_path = write_image_grid_spec(tmp_path)
    out = tmp_path / "output" / "deck.pptx"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--spec", str(spec_path), "--out", str(out)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    with zipfile.ZipFile(out) as package:
        slide_xml = package.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "First" in slide_xml
    assert "Second" in slide_xml


def test_build_deck_rejects_output_outside_workspace(tmp_path):
    require_node_builder()
    spec_path = write_image_grid_spec(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.pptx"

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--spec", str(spec_path), "--out", str(outside)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "escapes workspace" in result.stderr
    assert not outside.exists()
