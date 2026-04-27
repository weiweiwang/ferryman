import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE_SCRIPT_PATH = REPO_ROOT / "frontend" / "scripts" / "stage_backend_bundle.py"
VERIFY_SCRIPT_PATH = REPO_ROOT / "frontend" / "scripts" / "verify_release_bundle.py"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_skill(skills_root: Path, name: str) -> None:
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {name} description\n"
            "version: 1.0.0\n"
            "---\n"
        ),
        encoding="utf-8",
    )


def test_stage_backend_copy_skills_does_not_inject_smoke_skill(tmp_path, monkeypatch):
    stage_module = load_module("stage_backend_bundle_test", STAGE_SCRIPT_PATH)
    skills_src = tmp_path / "skills-src"
    skills_dst = tmp_path / "skills-dst"
    write_skill(skills_src, "real-skill")

    monkeypatch.setattr(stage_module, "SKILLS_SRC", skills_src)
    monkeypatch.setattr(stage_module, "SKILLS_DST", skills_dst)

    stage_module.copy_skills()

    assert (skills_dst / "real-skill" / "SKILL.md").exists()
    smoke_skill_name = stage_module.__dict__.get("BUNDLE_SMOKE_SKILL_NAME", "bundle-smoke-skill")
    assert not (skills_dst / smoke_skill_name).exists()


def test_pyinstaller_spec_bundles_tiktoken_cache_and_keeps_tiktoken():
    spec_text = (REPO_ROOT / "backend" / "ferryman_backend.spec").read_text(encoding="utf-8")

    assert "app/assets/tiktoken" in spec_text
    assert "fb374d419588a4632f3f557e76b4b70aebbca790" in spec_text
    assert '"tiktoken",' in spec_text.split("hiddenimports = sorted", 1)[1].split("datas = []", 1)[0]
    assert '"tiktoken",' not in spec_text.split("excludes=[", 1)[1].split("],", 1)[0]


def test_pyinstaller_spec_bundles_resend_and_optional_runtime_defaults():
    spec_text = (REPO_ROOT / "backend" / "ferryman_backend.spec").read_text(encoding="utf-8")

    assert '"resend",' in spec_text.split("hiddenimports = sorted", 1)[1].split("datas = []", 1)[0]
    assert "runtime_defaults.json" in spec_text
    assert "app/assets/defaults" in spec_text


def test_build_smoke_skills_dir_adds_temp_smoke_skill_only_for_verification(tmp_path):
    verify_module = load_module("verify_release_bundle_test", VERIFY_SCRIPT_PATH)
    packaged_skills_dir = tmp_path / "packaged-skills"
    packaged_skills_dir.mkdir(parents=True, exist_ok=True)
    write_skill(packaged_skills_dir, "real-skill")

    staged_skills_dir = verify_module.build_smoke_skills_dir(packaged_skills_dir, tmp_path / "staging-root")

    assert (packaged_skills_dir / "real-skill" / "SKILL.md").exists()
    assert not (packaged_skills_dir / verify_module.BUNDLE_SMOKE_SKILL_NAME).exists()
    assert (staged_skills_dir / "real-skill" / "SKILL.md").exists()
    assert (staged_skills_dir / verify_module.BUNDLE_SMOKE_SKILL_NAME / "SKILL.md").exists()
    assert (
        staged_skills_dir
        / verify_module.BUNDLE_SMOKE_SKILL_NAME
        / "scripts"
        / "verify_bundle_resources.py"
    ).exists()


def test_ensure_packaged_skills_clean_rejects_leaked_smoke_skill(tmp_path):
    verify_module = load_module("verify_release_bundle_test_leak", VERIFY_SCRIPT_PATH)
    packaged_skills_dir = tmp_path / "packaged-skills"
    packaged_skills_dir.mkdir(parents=True, exist_ok=True)
    write_skill(packaged_skills_dir, verify_module.BUNDLE_SMOKE_SKILL_NAME)

    with pytest.raises(RuntimeError, match="internal smoke skill"):
        verify_module.ensure_packaged_skills_clean(packaged_skills_dir)
