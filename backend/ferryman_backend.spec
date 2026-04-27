from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


PROJECT_ROOT = Path(SPECPATH).resolve().parents[0]
BACKEND_ROOT = PROJECT_ROOT / "backend"

hiddenimports = sorted(
    set(
        [
            "app.core.browser",
            "tiktoken",
            "tiktoken_ext.openai_public",
            "pydantic_ai.agent",
            "pydantic_ai.messages",
            "pydantic_ai.models.anthropic",
            "pydantic_ai.models.google",
            "pydantic_ai.models.openai",
            "pydantic_ai.providers.anthropic",
            "pydantic_ai.providers.google",
            "pydantic_ai.providers.openai",
            "pydantic_ai.tools",
            "pydantic_ai.usage",
            "playwright.__main__",
            "playwright._impl.__pyinstaller",
            "playwright._impl._path_utils",
            "playwright.async_api",
            "playwright.sync_api",
            "playwright_stealth",
            "pythonjsonlogger.orjson",
            "resend",
        ]
    )
)

datas = []
datas += collect_data_files("playwright_stealth", includes=["js/**/*.js"])
datas += collect_data_files("trafilatura", includes=["settings.cfg"])
datas += collect_data_files("justext", includes=["stoplists/*"])
datas.append(
    (
        str(BACKEND_ROOT / "app" / "assets" / "tiktoken" / "fb374d419588a4632f3f557e76b4b70aebbca790"),
        "app/assets/tiktoken",
    )
)
runtime_defaults = BACKEND_ROOT / "app" / "assets" / "defaults" / "runtime_defaults.json"
if runtime_defaults.exists():
    datas.append((str(runtime_defaults), "app/assets/defaults"))
for package_name in (
    "genai_prices",
    "pydantic_ai",
    "pydantic_ai_slim",
    "pydantic_graph",
    "pydantic_evals",
    "pydantic",
    "pydantic_core",
    "pydantic_settings",
):
    datas += copy_metadata(package_name)

a = Analysis(
    [str(BACKEND_ROOT / "app" / "sidecar.py")],
    pathex=[str(BACKEND_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "boto3",
        "botocore",
        "grpc",
        "hf_xet",
        "huggingface_hub",
        "keyring",
        "lancedb",
        "numpy",
        "pandas",
        "pyarrow",
        "pytest",
        "sentence_transformers",
        "temporalio",
        "tokenizers",
        "xai_sdk",
        "pydantic_ai.durable_exec",
        "pydantic_ai.embeddings.bedrock",
        "pydantic_ai.embeddings.openai",
        "pydantic_ai.embeddings.sentence_transformers",
        "pydantic_ai.models.alibaba",
        "pydantic_ai.models.azure",
        "pydantic_ai.models.bedrock",
        "pydantic_ai.models.cerebras",
        "pydantic_ai.models.cohere",
        "pydantic_ai.models.deepseek",
        "pydantic_ai.models.fireworks",
        "pydantic_ai.models.github",
        "pydantic_ai.models.grok",
        "pydantic_ai.models.groq",
        "pydantic_ai.models.huggingface",
        "pydantic_ai.models.litellm",
        "pydantic_ai.models.mistral",
        "pydantic_ai.models.moonshotai",
        "pydantic_ai.models.nebius",
        "pydantic_ai.models.ollama",
        "pydantic_ai.models.openrouter",
        "pydantic_ai.models.outlines",
        "pydantic_ai.models.ovhcloud",
        "pydantic_ai.models.sambanova",
        "pydantic_ai.models.vercel",
        "pydantic_ai.models.voyageai",
        "pydantic_ai.models.xai",
        "pydantic_ai.providers.alibaba",
        "pydantic_ai.providers.azure",
        "pydantic_ai.providers.bedrock",
        "pydantic_ai.providers.cerebras",
        "pydantic_ai.providers.cohere",
        "pydantic_ai.providers.deepseek",
        "pydantic_ai.providers.fireworks",
        "pydantic_ai.providers.gateway",
        "pydantic_ai.providers.github",
        "pydantic_ai.providers.grok",
        "pydantic_ai.providers.groq",
        "pydantic_ai.providers.heroku",
        "pydantic_ai.providers.huggingface",
        "pydantic_ai.providers.litellm",
        "pydantic_ai.providers.mistral",
        "pydantic_ai.providers.moonshotai",
        "pydantic_ai.providers.nebius",
        "pydantic_ai.providers.ollama",
        "pydantic_ai.providers.openrouter",
        "pydantic_ai.providers.outlines",
        "pydantic_ai.providers.ovhcloud",
        "pydantic_ai.providers.sambanova",
        "pydantic_ai.providers.sentence_transformers",
        "pydantic_ai.providers.together",
        "pydantic_ai.providers.vercel",
        "pydantic_ai.providers.voyageai",
        "pydantic_ai.providers.xai",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ferryman",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ferryman",
)
