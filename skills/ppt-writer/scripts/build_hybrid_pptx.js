#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const {
  H,
  W,
  createDeck,
  defaultOutputForSpec,
  fontFromSpec,
  normalizeImageFit,
  readJson,
  resolveInputPath,
  themeFromSpec,
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
    "  node scripts/build_hybrid_pptx.js --spec <deck-spec.json> --layout <layout.json> [--out <deck.pptx>] [--editable-layer none|visible]",
    "",
    "Builds a hybrid PPTX from rendered HTML backgrounds plus editable DOM objects.",
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
    const enriched = new Error(
      [
        "Missing dependency: pptxgenjs.",
        "Install/package this skill's Node dependencies before building decks:",
        "  npm ci --prefix skills/ppt-writer",
        "",
        `Original error: ${error.message}`,
      ].join("\n")
    );
    enriched.cause = error;
    throw enriched;
  }
}

function cssColorToHex(value, fallback = "000000") {
  const raw = String(value || "").trim();
  if (!raw || raw === "transparent") return fallback;
  const hex = raw.match(/^#([0-9a-fA-F]{6})$/);
  if (hex) return hex[1].toUpperCase();
  const rgba = raw.match(/^rgba?\(([^)]+)\)$/);
  if (rgba) {
    const parts = rgba[1].split(",").map((part) => part.trim());
    const alpha = parts.length >= 4 ? Number.parseFloat(parts[3]) : 1;
    if (Number.isFinite(alpha) && alpha <= 0.02) return fallback;
    const nums = parts.slice(0, 3).map((part) => Math.max(0, Math.min(255, Number.parseInt(part, 10) || 0)));
    return nums.map((num) => num.toString(16).padStart(2, "0")).join("").toUpperCase();
  }
  return fallback;
}

function cssAlpha(value) {
  const raw = String(value || "").trim();
  const rgba = raw.match(/^rgba?\(([^)]+)\)$/);
  if (!rgba) return 1;
  const parts = rgba[1].split(",").map((part) => part.trim());
  if (parts.length < 4) return 1;
  const alpha = Number.parseFloat(parts[3]);
  return Number.isFinite(alpha) ? Math.max(0, Math.min(1, alpha)) : 1;
}

function px(value, fallback = 0) {
  const parsed = Number.parseFloat(String(value || ""));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function rectToInches(rect, layout) {
  const pxW = layout.slide_width_px || 1280;
  const pxH = layout.slide_height_px || 720;
  return {
    x: (rect.x / pxW) * W,
    y: (rect.y / pxH) * H,
    w: (rect.w / pxW) * W,
    h: (rect.h / pxH) * H,
  };
}

function fontSizePt(element) {
  const cssPx = px(element.style && element.style.fontSize, 16);
  return Math.max(6, Math.min(54, cssPx * 0.75));
}

function isBold(element) {
  const weight = String((element.style && element.style.fontWeight) || "");
  if (weight === "bold" || weight === "bolder") return true;
  const numeric = Number.parseInt(weight, 10);
  return Number.isFinite(numeric) && numeric >= 650;
}

function fontFace(element, fallback) {
  const raw = String((element.style && element.style.fontFamily) || "").split(",")[0].replace(/["']/g, "").trim();
  return raw || fallback;
}

function addShape(pptx, slide, element, box, colors) {
  const bg = (element.style && element.style.backgroundColor) || "";
  const bgAlpha = cssAlpha(bg);
  const fillColor = cssColorToHex(bg, colors.white);
  const borderColor = cssColorToHex(element.style && element.style.borderColor, colors.hair);
  const borderWidth = Math.max(0.25, px(element.style && element.style.borderWidth, 1) * 0.55);
  slide.addShape(pptx.ShapeType.roundRect, {
    ...box,
    rectRadius: 0.04,
    fill: { color: fillColor, transparency: Math.round((1 - bgAlpha) * 100) },
    line: { color: borderColor, width: borderWidth, transparency: bgAlpha <= 0.02 ? 100 : 15 },
  });
}

function addNativeText(slide, element, box, font) {
  const text = String(element.text || "").trim();
  if (!text) return;
  const color = cssColorToHex(element.style && element.style.color, "111111");
  const align = String((element.style && element.style.textAlign) || "left");
  const type = String(element.type || "");
  slide.addText(text, {
    ...box,
    fontFace: fontFace(element, type === "title" ? font.head : font.body),
    fontSize: fontSizePt(element),
    color,
    bold: isBold(element) || type === "title" || type === "metric",
    margin: type === "footer" ? 0 : 0.02,
    fit: "shrink",
    breakLine: false,
    valign: "top",
    align: ["center", "right"].includes(align) ? align : "left",
    paraSpaceAfterPt: 2,
  });
}

function resolveElementImagePath(element) {
  const raw = element && element.data && (element.data.path || element.data.src);
  if (raw) return resolveInputPath(raw);
  const currentSrc = element.currentSrc || "";
  if (currentSrc.startsWith("file://")) {
    return decodeURIComponent(new URL(currentSrc).pathname);
  }
  throw new Error(`Editable image element is missing data-path: ${JSON.stringify(element).slice(0, 300)}`);
}

function addNativeImage(slide, element, box) {
  const imagePath = resolveElementImagePath(element);
  if (!fs.existsSync(imagePath)) {
    throw new Error(`Editable image file not found: ${imagePath}`);
  }
  const fit = normalizeImageFit((element.data && element.data.fit) || (element.style && element.style.objectFit), "cover");
  slide.addImage({
    path: imagePath,
    ...box,
    altText: (element.data && element.data.alt) || element.text || "",
    sizing: { type: fit, w: box.w, h: box.h },
  });
}

function addElement(pptx, slide, element, layout, colors, font) {
  const box = rectToInches(element.rect || {}, layout);
  if (box.w <= 0 || box.h <= 0) return;
  const type = String(element.type || "text");
  if (type === "image" || element.tag === "img") {
    addNativeImage(slide, element, box);
    return;
  }
  if (type === "shape" || type === "card" || type === "panel") {
    addShape(pptx, slide, element, box, colors);
    return;
  }
  addNativeText(slide, element, box, font);
}

function elementSort(a, b) {
  const shapeA = ["shape", "card", "panel"].includes(String(a.type || ""));
  const shapeB = ["shape", "card", "panel"].includes(String(b.type || ""));
  if (shapeA !== shapeB) return shapeA ? -1 : 1;
  return (a.order || 0) - (b.order || 0);
}

function imageElementMetrics(elements, layout) {
  const pxW = layout.slide_width_px || 1280;
  const pxH = layout.slide_height_px || 720;
  const slideArea = Math.max(1, pxW * pxH);
  const imageAreas = elements
    .filter((element) => String(element.type || "") === "image" || element.tag === "img")
    .map((element) => {
      const rect = element.rect || {};
      const w = Math.max(0, Number(rect.w) || 0);
      const h = Math.max(0, Number(rect.h) || 0);
      return (w * h) / slideArea;
    })
    .filter((value) => value > 0);
  return {
    count: imageAreas.length,
    totalArea: imageAreas.reduce((sum, value) => sum + value, 0),
    maxArea: imageAreas.length ? Math.max(...imageAreas) : 0,
  };
}

function backgroundAltText(renderedSlide, elements, layout) {
  const mode = String(renderedSlide.background_mode || layout.background_mode || "visual");
  const imageMetrics = imageElementMetrics(elements, layout);
  const marker = mode === "visual" ? "FERRYMAN_HYBRID_VISUAL_BACKGROUND" : "FERRYMAN_HYBRID_BACKGROUND";
  return [
    marker,
    `content_images=${imageMetrics.count}`,
    `content_image_area=${imageMetrics.totalArea.toFixed(4)}`,
    `max_content_image_area=${imageMetrics.maxArea.toFixed(4)}`,
  ].join(";");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.spec || !args.layout) {
    console.log(usage());
    process.exit(args.help ? 0 : 2);
  }

  const specPath = resolveWorkspacePath(args.spec, "--spec");
  const layoutPath = resolveWorkspacePath(args.layout, "--layout");
  const spec = readJson(specPath);
  const layout = readJson(layoutPath);
  if (!Array.isArray(layout.slides) || !layout.slides.length) {
    throw new Error("Layout JSON must include rendered slides.");
  }
  const editableLayer = String(args["editable-layer"] || "visible");
  if (!["none", "visible"].includes(editableLayer)) {
    throw new Error("--editable-layer must be none or visible.");
  }

  const out = resolveWorkspacePath(args.out || defaultOutputForSpec(specPath, spec), "--out");
  const pptxgen = requirePptxgen();
  const deck = createDeck(pptxgen, spec);
  const colors = themeFromSpec(spec);
  const font = fontFromSpec(spec);

  layout.slides.forEach((renderedSlide) => {
    const slide = deck.addSlide();
    const backgroundPath = resolveWorkspacePath(renderedSlide.background, "rendered slide background");
    if (!fs.existsSync(backgroundPath)) {
      throw new Error(`Rendered slide background not found: ${backgroundPath}`);
    }
    const elements = Array.isArray(renderedSlide.elements) ? renderedSlide.elements : [];
    slide.addImage({
      path: backgroundPath,
      x: 0,
      y: 0,
      w: W,
      h: H,
      altText: backgroundAltText(renderedSlide, elements, layout),
      sizing: { type: "cover", w: W, h: H },
    });
    if (editableLayer === "visible") {
      elements.slice().sort(elementSort).forEach((element) => addElement(deck, slide, element, layout, colors, font));
    }
  });

  fs.mkdirSync(path.dirname(out), { recursive: true });
  await deck.writeFile({ fileName: out });
  const stat = fs.statSync(out);
  if (!stat.size) throw new Error(`Output PPTX is empty: ${out}`);
  console.log(JSON.stringify({
    ok: true,
    spec: specPath,
    layout: layoutPath,
    output: out,
    output_bytes: stat.size,
    slide_count: layout.slides.length,
    mode: "hybrid",
    editable_layer: editableLayer,
  }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  console.error(usage());
  process.exit(1);
});
