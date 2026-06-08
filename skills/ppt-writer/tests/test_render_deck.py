import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_deck.py"


def load_module():
    spec = importlib.util.spec_from_file_location("render_deck", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_resolve_workspace_path_rejects_escape(tmp_path):
    module = load_module()
    outside = tmp_path.parent / "outside.pptx"

    try:
        module.resolve_workspace_path(outside, workspace=tmp_path, label="PPTX path")
    except ValueError as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("Expected workspace escape to be rejected.")


def test_clean_render_output_dir_removes_stale_slide_pngs(tmp_path):
    module = load_module()
    output_dir = tmp_path / "preview"
    output_dir.mkdir()
    stale = output_dir / "slide-08.png"
    keep = output_dir / "notes.txt"
    stale.write_bytes(b"old")
    keep.write_text("keep", encoding="utf-8")

    module.clean_render_output_dir(output_dir)

    assert not stale.exists()
    assert keep.exists()
