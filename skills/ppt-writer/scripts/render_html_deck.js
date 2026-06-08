#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const { H, W, readJson } = require("./pptx_helpers");

const PX_W = 1280;
const PX_H = 720;

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
    "  node scripts/render_html_deck.js --manifest <deck-html-manifest.json> --out-dir <preview-dir> --layout-out <layout.json> [--background-mode visual|skeleton]",
    "",
    "Renders controlled slide HTML with Chromium and extracts DOM layout for hybrid PPTX output.",
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

function cleanSlidePreviews(outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  for (const name of fs.readdirSync(outDir)) {
    if (/^slide-\d+\.png$/i.test(name)) {
      fs.unlinkSync(path.join(outDir, name));
    }
  }
}

function loadPlaywright() {
  try {
    return require("playwright-core");
  } catch (coreError) {
    try {
      return require("playwright");
    } catch {
      const error = new Error(
        [
          "Missing dependency: playwright-core.",
          "Install/package the skill dependency with npm ci --prefix skills/ppt-writer.",
          `Original error: ${coreError.message}`,
        ].join("\n")
      );
      error.cause = coreError;
      throw error;
    }
  }
}

function findBrowserExecutable() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    process.env.CHROME_BIN,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate));
}

async function launchBrowser(playwright) {
  const executablePath = findBrowserExecutable();
  const options = {
    headless: true,
    args: ["--allow-file-access-from-files", "--disable-dev-shm-usage"],
  };
  if (executablePath) options.executablePath = executablePath;
  return playwright.chromium.launch(options);
}

async function extractElements(page) {
  return page.$$eval("[data-pptx]", (nodes) => {
    function styleValue(style, name) {
      return style.getPropertyValue(name) || "";
    }
    return nodes.map((node, order) => {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      const data = {};
      Array.from(node.attributes).forEach((attr) => {
        if (attr.name.startsWith("data-")) {
          data[attr.name.replace(/^data-/, "")] = attr.value;
        }
      });
      const isImage = node.tagName.toLowerCase() === "img";
      const type = node.getAttribute("data-pptx") || "text";
      const shapeOnly = type === "shape" || type === "card" || type === "panel";
      const text = shapeOnly ? "" : (node.innerText || node.textContent || "").trim();
      const overflowX = Math.max(0, node.scrollWidth - node.clientWidth);
      const overflowY = Math.max(0, node.scrollHeight - node.clientHeight);
      const textOverflow = Boolean(text && !isImage && (overflowX > 2 || overflowY > 2));
      return {
        order,
        type,
        tag: node.tagName.toLowerCase(),
        text,
        src: isImage ? node.getAttribute("src") : "",
        currentSrc: isImage ? node.currentSrc : "",
        data,
        rect: {
          x: rect.x,
          y: rect.y,
          w: rect.width,
          h: rect.height,
        },
        overflow: {
          x: overflowX,
          y: overflowY,
          scrollWidth: node.scrollWidth,
          scrollHeight: node.scrollHeight,
          clientWidth: node.clientWidth,
          clientHeight: node.clientHeight,
          textOverflow,
        },
        style: {
          color: style.color,
          backgroundColor: style.backgroundColor,
          borderColor: style.borderColor,
          borderWidth: style.borderWidth,
          borderRadius: style.borderRadius,
          fontFamily: style.fontFamily,
          fontSize: style.fontSize,
          fontWeight: style.fontWeight,
          lineHeight: style.lineHeight,
          textAlign: style.textAlign,
          objectFit: styleValue(style, "object-fit"),
          opacity: style.opacity,
          zIndex: style.zIndex,
        },
      };
    }).filter((item) => item.rect.w > 0 && item.rect.h > 0);
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.manifest || !args["out-dir"] || !args["layout-out"]) {
    console.log(usage());
    process.exit(args.help ? 0 : 2);
  }

  const manifestPath = resolveWorkspacePath(args.manifest, "--manifest");
  const outDir = resolveWorkspacePath(args["out-dir"], "--out-dir");
  const layoutOut = resolveWorkspacePath(args["layout-out"], "--layout-out");
  const backgroundMode = String(args["background-mode"] || "skeleton");
  if (!["visual", "skeleton"].includes(backgroundMode)) {
    throw new Error("--background-mode must be visual or skeleton.");
  }
  const manifest = readJson(manifestPath);
  if (!Array.isArray(manifest.slides) || !manifest.slides.length) {
    throw new Error("HTML manifest must include slides.");
  }

  cleanSlidePreviews(outDir);
  const playwright = loadPlaywright();
  const browser = await launchBrowser(playwright);
  const page = await browser.newPage({ viewport: { width: PX_W, height: PX_H }, deviceScaleFactor: 2 });
  const slides = [];

  try {
    for (const slide of manifest.slides) {
      const htmlPath = resolveWorkspacePath(slide.file, "manifest slide.file");
      await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
      const elements = await extractElements(page);
      if (backgroundMode === "skeleton") {
        await page.addStyleTag({
          content: [
            "[data-pptx]{visibility:hidden!important}",
            "[data-raster='true']{visibility:visible!important}",
          ].join("\n"),
        });
      }
      const pngName = `slide-${String(slide.number).padStart(2, "0")}.png`;
      const pngPath = path.join(outDir, pngName);
      await page.screenshot({
        path: pngPath,
        clip: { x: 0, y: 0, width: PX_W, height: PX_H },
        omitBackground: false,
      });
      slides.push({
        number: slide.number,
        layout: slide.layout,
        html: path.relative(process.cwd(), htmlPath),
        background: path.relative(process.cwd(), pngPath),
        background_mode: backgroundMode,
        elements,
      });
    }
  } finally {
    await page.close().catch(() => undefined);
    await browser.close().catch(() => undefined);
  }

  const overflowWarnings = [];
  for (const slide of slides) {
    for (const element of slide.elements || []) {
      const overflow = element.overflow || {};
      if (overflow.textOverflow) {
        overflowWarnings.push({
          slide: slide.number,
          type: element.type,
          text: String(element.text || "").slice(0, 80),
          overflow_x: overflow.x,
          overflow_y: overflow.y,
        });
      }
    }
  }

  const layout = {
    ok: true,
    manifest: path.relative(process.cwd(), manifestPath),
    slide_width_px: PX_W,
    slide_height_px: PX_H,
    pptx_width_in: W,
    pptx_height_in: H,
    background_mode: backgroundMode,
    overflow_warnings: overflowWarnings,
    overflow_warning_count: overflowWarnings.length,
    slides,
  };
  fs.mkdirSync(path.dirname(layoutOut), { recursive: true });
  fs.writeFileSync(layoutOut, `${JSON.stringify(layout, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({
    ok: true,
    manifest: path.relative(process.cwd(), manifestPath),
    layout: path.relative(process.cwd(), layoutOut),
    out_dir: path.relative(process.cwd(), outDir),
    background_mode: backgroundMode,
    slide_count: slides.length,
    overflow_warning_count: overflowWarnings.length,
    overflow_warnings: overflowWarnings.slice(0, 10),
  }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  console.error(usage());
  process.exit(1);
});
