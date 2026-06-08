import importlib.util
import base64
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "register_asset.py"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def load_module():
    spec = importlib.util.spec_from_file_location("register_asset", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_register_asset_copies_image_and_updates_manifest(tmp_path):
    module = load_module()
    source_dir = tmp_path / "screenshots"
    source_dir.mkdir()
    source = source_dir / "capture.png"
    source.write_bytes(PNG_1X1)

    result = module.register_asset(
        source="screenshots/capture.png",
        asset_id="Cover Hero",
        asset_dir="reports/task/assets",
        manifest_path="reports/task/asset-manifest.json",
        source_note="https://example.test",
        role="cover hero",
        alt="Handshake photo",
        workspace=tmp_path,
    )

    assert result["ok"] is True
    assert result["asset"]["id"] == "cover-hero"
    assert result["asset"]["path"] == "reports/task/assets/cover-hero.png"
    assert result["asset"]["width"] == 1
    assert result["asset"]["height"] == 1
    assert result["asset"]["format"] == "PNG"
    assert result["asset"]["aspect_ratio"] == 1
    assert result["asset"]["bytes"] == len(PNG_1X1)
    assert (tmp_path / result["asset"]["path"]).read_bytes() == PNG_1X1
    manifest = (tmp_path / "reports/task/asset-manifest.json").read_text(encoding="utf-8")
    assert "cover-hero" in manifest
    assert "https://example.test" in manifest
    assert "\"width\": 1" in manifest


def test_register_asset_rejects_workspace_escape(tmp_path):
    module = load_module()
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"fake jpeg")

    try:
        module.register_asset(
            source=outside,
            asset_id="outside",
            asset_dir="assets",
            manifest_path="asset-manifest.json",
            workspace=tmp_path,
        )
    except ValueError as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("Expected workspace escape to be rejected.")
