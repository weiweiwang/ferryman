#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const {
  buildDeckFromSpec,
  defaultOutputForSpec,
  readJson,
} = require("./pptx_helpers");

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unexpected positional argument: ${key}`);
    const value = argv[i + 1];
    if (!value || value.startsWith("--")) {
      args[key.slice(2)] = true;
    } else {
      args[key.slice(2)] = value;
      i += 1;
    }
  }
  return args;
}

function usage() {
  return [
    "Usage:",
    "  node scripts/build_deck.js --spec <deck-spec.json> [--out <deck.pptx>]",
    "",
    "Options:",
    "  --spec <path>        Workspace-relative or absolute deck spec JSON.",
    "  --out <path>         Output PPTX path. Defaults to output/<title>.pptx next to spec.",
  ].join("\n");
}

function resolveWorkspacePath(rawPath, label) {
  if (!rawPath || typeof rawPath !== "string") throw new Error(`${label} is required.`);
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(rawPath)) {
    throw new Error(`${label} must be a workspace file path, not a URL: ${rawPath}`);
  }
  const resolved = path.isAbsolute(rawPath) ? path.resolve(rawPath) : path.resolve(process.cwd(), rawPath);
  const relative = path.relative(process.cwd(), resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label} escapes workspace: ${rawPath}`);
  }
  return resolved;
}

function requirePptxgen() {
  try {
    return require("pptxgenjs");
  } catch (error) {
    const message = [
      "Missing dependency: pptxgenjs.",
      "Install or package this skill's Node dependency before building decks:",
      "  npm install --prefix <skill_dir>",
      "",
      `Original error: ${error.message}`,
    ].join("\n");
    const enriched = new Error(message);
    enriched.cause = error;
    throw enriched;
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.spec) {
    console.log(usage());
    process.exit(args.help ? 0 : 2);
  }

  const specPath = resolveWorkspacePath(args.spec, "--spec");
  const spec = readJson(specPath);
  const out = resolveWorkspacePath(args.out || defaultOutputForSpec(specPath, spec), "--out");
  const pptxgen = requirePptxgen();
  const deck = buildDeckFromSpec(pptxgen, spec);

  fs.mkdirSync(path.dirname(out), { recursive: true });
  await deck.writeFile({ fileName: out });

  const stat = fs.statSync(out);
  if (!stat.size) throw new Error(`Output PPTX is empty: ${out}`);

  const result = {
    ok: true,
    spec: specPath,
    output: out,
    output_bytes: stat.size,
    slide_count: Array.isArray(spec.slides) ? spec.slides.length : 0,
  };
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  console.error(usage());
  process.exit(1);
});
