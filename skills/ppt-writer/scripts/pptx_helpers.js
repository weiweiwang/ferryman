"use strict";

const fs = require("fs");
const path = require("path");
const imageSize = require("image-size");

const W = 13.333;
const H = 7.5;

const DEFAULT_THEME = {
  paper: "F5F2EA",
  ink: "141A17",
  muted: "59635E",
  hair: "D8D2C4",
  dark: "111A16",
  green: "1F6B4B",
  mint: "DCEADE",
  blue: "255D78",
  sky: "DCE9EE",
  amber: "B8791E",
  sand: "E9DCC6",
  red: "944B3D",
  accent: "944B3D",
  accent2: "255D78",
  gold: "B8791E",
  white: "FFFFFF",
  black: "000000",
};

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function slugify(value, fallback = "deck") {
  const slug = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/['"]/g, "")
    .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return slug || fallback;
}

function isUrlLike(value) {
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(String(value || ""));
}

function assertInsideWorkspace(resolvedPath, label = "path") {
  const workspace = process.cwd();
  const relative = path.relative(workspace, resolvedPath);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label} escapes workspace: ${resolvedPath}`);
  }
}

function resolveInputPath(value) {
  if (!value) return undefined;
  const raw = String(value);
  if (isUrlLike(raw)) {
    throw new Error(`Image path must be a workspace file path, not a URL: ${raw}`);
  }
  const resolved = path.isAbsolute(raw) ? path.resolve(raw) : path.resolve(process.cwd(), raw);
  assertInsideWorkspace(resolved, "Image path");
  return resolved;
}

function normalizeItems(items) {
  if (!Array.isArray(items)) return [];
  return items.map((item) => {
    if (typeof item === "string") return { label: item, text: "" };
    return item && typeof item === "object" ? item : { label: String(item), text: "" };
  });
}

function normalizeImages(slideSpec) {
  const images = [];
  if (slideSpec.image && typeof slideSpec.image === "object") images.push(slideSpec.image);
  if (Array.isArray(slideSpec.images)) {
    slideSpec.images.forEach((image) => {
      if (image && typeof image === "object") images.push(image);
    });
  }
  return images;
}

function imageDimensionsInches(imagePath, fallbackW, fallbackH) {
  try {
    const dimensions = imageSize(imagePath);
    if (dimensions && dimensions.width && dimensions.height) {
      const ratio = dimensions.width / dimensions.height;
      return ratio >= 1 ? { w: ratio, h: 1 } : { w: 1, h: 1 / ratio };
    }
  } catch {
    // Fall back to the target box when image-size cannot read the asset.
  }
  return { w: fallbackW, h: fallbackH };
}

function normalizeImageFit(value, fallback = "cover") {
  const fit = String(value || fallback).toLowerCase();
  return ["cover", "contain", "crop"].includes(fit) ? fit : fallback;
}

function hasImage(slideSpec) {
  return normalizeImages(slideSpec).length > 0;
}

function themeFromSpec(spec) {
  const nestedTheme = spec.theme && typeof spec.theme === "object" ? spec.theme : {};
  const customColors = {
    ...((nestedTheme.colors && typeof nestedTheme.colors === "object") ? nestedTheme.colors : {}),
    ...((spec.colors && typeof spec.colors === "object") ? spec.colors : {}),
  };
  const colors = { ...DEFAULT_THEME, ...customColors };
  if (customColors.bg && !customColors.paper) colors.paper = customColors.bg;
  colors.accent = colors.accent || colors.red;
  colors.accent2 = colors.accent2 || colors.blue;
  colors.gold = colors.gold || colors.amber;
  return colors;
}

function fontFromSpec(spec) {
  const nestedTheme = spec.theme && typeof spec.theme === "object" ? spec.theme : {};
  const nestedFont = nestedTheme.font && typeof nestedTheme.font === "object" ? nestedTheme.font : {};
  const language = String(spec.language || "zh-CN").toLowerCase();
  if (language.startsWith("zh")) {
    return {
      head: spec.head_font || nestedFont.heading || nestedFont.head || "PingFang SC",
      body: spec.body_font || nestedFont.body || "PingFang SC",
      lang: spec.language || "zh-CN",
    };
  }
  return {
    head: spec.head_font || nestedFont.heading || nestedFont.head || "Aptos Display",
    body: spec.body_font || nestedFont.body || "Aptos",
    lang: spec.language || "en-US",
  };
}

function addBg(pptx, slide, colors, tone = "light") {
  const color = tone === "dark" ? colors.dark : colors.paper;
  slide.background = { color };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: W,
    h: H,
    fill: { color },
    line: { color },
  });
}

function addText(slide, value, x, y, w, h, opt = {}) {
  slide.addText(String(value || ""), {
    x,
    y,
    w,
    h,
    fontFace: opt.fontFace,
    fontSize: opt.size ?? 14,
    color: opt.color,
    bold: Boolean(opt.bold),
    margin: opt.margin ?? 0.03,
    fit: opt.fit || "shrink",
    valign: opt.valign || "top",
    breakLine: false,
    align: opt.align,
    paraSpaceAfterPt: opt.paraSpaceAfterPt,
    bullet: opt.bullet,
    ...opt.extra,
  });
}

function addRule(pptx, slide, x, y, w, color, width = 0.8) {
  slide.addShape(pptx.ShapeType.line, {
    x,
    y,
    w,
    h: 0,
    line: { color, width },
  });
}

function addPanel(pptx, slide, x, y, w, h, colors, opt = {}) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: opt.radius ?? 0.04,
    fill: { color: opt.fill || colors.white },
    line: { color: opt.line || colors.hair, transparency: opt.lineTransparency ?? 12 },
  });
}

function addImage(pptx, slide, imageSpec, x, y, w, h, colors, font, opt = {}) {
  const imagePath = resolveInputPath(imageSpec.path || imageSpec.src);
  if (!imagePath) {
    throw new Error(`Image is missing path/src: ${JSON.stringify(imageSpec)}`);
  }
  if (!fs.existsSync(imagePath)) {
    throw new Error(`Image file not found: ${imagePath}`);
  }
  const lineColor = opt.line || colors.hair;
  if (opt.frame !== false) {
    slide.addShape(pptx.ShapeType.rect, {
      x,
      y,
      w,
      h,
      fill: { color: colors.white, transparency: 100 },
      line: { color: lineColor, transparency: 15 },
    });
  }
  const fit = normalizeImageFit(imageSpec.fit || opt.fit, opt.fit || "cover");
  const natural = imageDimensionsInches(imagePath, w, h);
  const imageOptions = {
    path: imagePath,
    x,
    y,
    w: natural.w,
    h: natural.h,
    altText: imageSpec.alt || imageSpec.caption || imageSpec.source || "",
    sizing: { type: fit, w, h },
  };
  if (fit === "crop" && imageSpec.crop && typeof imageSpec.crop === "object") {
    imageOptions.sizing = {
      type: "crop",
      w,
      h,
      x: imageSpec.crop.x || 0,
      y: imageSpec.crop.y || 0,
    };
  }
  slide.addImage(imageOptions);
  const caption = imageSpec.caption || imageSpec.source;
  if (caption && opt.caption !== false) {
    addText(slide, caption, x, y + h + 0.08, w, 0.16, {
      size: 7.2,
      color: opt.captionColor || colors.muted,
      margin: 0,
      fontFace: font.body,
    });
  }
}

function addArrow(pptx, slide, x1, y1, x2, y2, color, width = 1.4) {
  slide.addShape(pptx.ShapeType.line, {
    x: x1,
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: { color, width, endArrowType: "triangle" },
  });
}

function addKicker(pptx, slide, value, x, y, colors, font) {
  const text = value || "PRESENTATION";
  slide.addShape(pptx.ShapeType.rect, {
    x,
    y: y + 0.17,
    w: 0.28,
    h: 0.03,
    fill: { color: colors.green },
    line: { color: colors.green },
  });
  addText(slide, text, x + 0.38, y, 3.2, 0.18, {
    size: 8.5,
    color: colors.green,
    bold: true,
    margin: 0,
    fontFace: font.body,
  });
}

function addFooter(slide, number, colors, font, dark = false) {
  addText(slide, String(number).padStart(2, "0"), 12.16, 7.04, 0.45, 0.12, {
    size: 7.5,
    color: dark ? "A9B8AE" : colors.muted,
    margin: 0,
    align: "right",
    fontFace: font.body,
  });
}

function addTitleBlock(pptx, slide, slideSpec, colors, font) {
  addKicker(pptx, slide, slideSpec.kicker || slideSpec.type || "SLIDE", 0.72, 0.45, colors, font);
  addText(slide, slideSpec.claim || slideSpec.title || "Untitled slide", 0.72, 0.78, 10.9, 0.62, {
    size: 24,
    bold: true,
    color: colors.ink,
    margin: 0,
    fontFace: font.head,
  });
  if (slideSpec.support) {
    addText(slide, slideSpec.support, 0.74, 1.34, 9.8, 0.34, {
      size: 11.5,
      color: colors.muted,
      margin: 0,
      fontFace: font.body,
    });
  }
}

function coverProcess(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors, "dark");
  const coverImages = normalizeImages(slideSpec);
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: W,
    h: 0.12,
    fill: { color: colors.amber },
    line: { color: colors.amber },
  });
  addText(slide, slideSpec.claim || slideSpec.title || "Untitled deck", 0.75, 1.05, coverImages.length ? 7.0 : 8.7, 1.35, {
    size: 32,
    bold: true,
    color: colors.white,
    margin: 0,
    fontFace: font.head,
  });
  addText(slide, slideSpec.body || slideSpec.support || "", 0.78, 2.78, 7.6, 0.72, {
    size: 13.2,
    color: "DDE8E0",
    margin: 0,
    fontFace: font.body,
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.78,
    y: 3.84,
    w: 1.5,
    h: 0.045,
    fill: { color: colors.amber },
    line: { color: colors.amber },
  });
  if (coverImages.length) {
    addImage(pptx, slide, coverImages[0], 8.55, 0.82, 3.92, 3.05, colors, font, {
      frame: false,
      captionColor: "A9B8AE",
      fit: "cover",
    });
  }
  const items = normalizeItems(slideSpec.items).slice(0, 3);
  const fallback = [
    { label: "Input", text: "Source" },
    { label: "Build", text: "System" },
    { label: "Output", text: "Result" },
  ];
  const processItems = items.length ? items : fallback;
  processItems.forEach((item, itemIndex) => {
    const x = 0.78 + itemIndex * 3.38;
    addPanel(pptx, slide, x, 5.55, 3.05, 0.82, colors, {
      fill: "17251F",
      line: "2A4034",
      lineTransparency: 0,
    });
    addText(slide, item.label, x + 0.26, 5.75, 0.95, 0.16, {
      size: 8.5,
      color: colors.amber,
      bold: true,
      margin: 0,
      fontFace: font.body,
    });
    addText(slide, item.text || item.value || item.label, x + 1.08, 5.70, 1.55, 0.24, {
      size: 13.2,
      color: colors.white,
      bold: true,
      margin: 0,
      fontFace: font.body,
    });
  });
  addFooter(slide, index, colors, font, true);
  return slide;
}

function bigClaim(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  const images = normalizeImages(slideSpec);
  addKicker(pptx, slide, slideSpec.kicker || "THESIS", 0.72, 0.55, colors, font);
  addText(slide, slideSpec.claim || "Untitled claim", 0.72, 1.08, 10.7, 1.25, {
    size: 30,
    bold: true,
    color: colors.ink,
    margin: 0,
    fontFace: font.head,
  });
  addRule(pptx, slide, 0.78, 2.92, 11.7, colors.hair);
  if (images.length) {
    addImage(pptx, slide, images[0], 8.65, 3.12, 3.35, 2.25, colors, font);
  }
  const items = normalizeItems(slideSpec.items).slice(0, images.length ? 3 : 4);
  const width = items.length >= 4 ? 2.75 : 3.25;
  const gap = items.length >= 4 ? 2.95 : 4.05;
  items.forEach((item, itemIndex) => {
    const x = 0.95 + itemIndex * gap;
    addText(slide, `0${itemIndex + 1}`, x, 3.45, 0.45, 0.16, {
      size: 9,
      color: [colors.green, colors.blue, colors.amber, colors.red][itemIndex % 4],
      bold: true,
      margin: 0,
      fontFace: font.body,
    });
    addText(slide, item.label || item.value || "", x, 3.78, width, 0.26, {
      size: 18,
      bold: true,
      color: colors.ink,
      margin: 0,
      fontFace: font.head,
    });
    addText(slide, item.text || item.note || "", x, 4.27, width, 0.62, {
      size: 11.2,
      color: colors.muted,
      margin: 0,
      fontFace: font.body,
    });
  });
  if (slideSpec.support) {
    addText(slide, slideSpec.support, 0.95, 6.05, 10.8, 0.32, {
      size: 13,
      bold: true,
      color: colors.green,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
  }
  addFooter(slide, index, colors, font);
  return slide;
}

function twoColumnCompare(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  addTitleBlock(pptx, slide, slideSpec, colors, font);
  const items = normalizeItems(slideSpec.items).slice(0, 2);
  const fallback = [
    { label: "Option A", text: "" },
    { label: "Option B", text: "" },
  ];
  const panels = items.length ? items : fallback;
  panels.forEach((item, itemIndex) => {
    const x = itemIndex === 0 ? 0.85 : 6.95;
    const accent = itemIndex === 0 ? colors.green : colors.blue;
    addPanel(pptx, slide, x, 2.0, 5.55, 3.55, colors, { fill: colors.white });
    addText(slide, item.label || "", x + 0.34, 2.34, 3.5, 0.26, {
      size: 19,
      bold: true,
      color: accent,
      margin: 0,
      fontFace: font.head,
    });
    addText(slide, item.text || item.body || "", x + 0.34, 2.92, 4.65, 1.3, {
      size: 12,
      color: colors.ink,
      margin: 0,
      fontFace: font.body,
    });
    const itemImages = normalizeImages(item);
    if (itemImages.length) {
      addImage(pptx, slide, itemImages[0], x + 0.34, 4.22, 2.1, 0.92, colors, font, {
        caption: false,
        fit: "contain",
      });
    }
    const metrics = normalizeItems(item.metrics).slice(0, 3);
    metrics.forEach((metric, metricIndex) => {
      const mx = x + 0.42 + metricIndex * 1.7;
      addText(slide, metric.value || metric.label || "", mx, 4.55, 1.3, 0.28, {
        size: 20,
        bold: true,
        color: [colors.green, colors.blue, colors.amber][metricIndex % 3],
        margin: 0,
        align: "center",
        fontFace: font.head,
      });
      addText(slide, metric.label || metric.text || "", mx - 0.1, 4.95, 1.5, 0.18, {
        size: 8.5,
        color: colors.muted,
        margin: 0,
        align: "center",
        fontFace: font.body,
      });
    });
  });
  addFooter(slide, index, colors, font);
  return slide;
}

function horizontalFlow(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  addTitleBlock(pptx, slide, slideSpec, colors, font);
  const items = normalizeItems(slideSpec.items).slice(0, 7);
  const count = Math.max(items.length, 1);
  const boxW = Math.min(1.85, 10.9 / count);
  const gap = count > 1 ? (10.9 - boxW * count) / (count - 1) : 0;
  items.forEach((item, itemIndex) => {
    const x = 1.0 + itemIndex * (boxW + gap);
    const fill = itemIndex % 2 ? colors.sky : colors.mint;
    addPanel(pptx, slide, x, 3.0, boxW, 1.15, colors, { fill, line: colors.hair });
    addText(slide, item.label || item.value || "", x + 0.1, 3.22, boxW - 0.2, 0.25, {
      size: 12,
      bold: true,
      color: colors.ink,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
    addText(slide, item.text || "", x + 0.13, 3.58, boxW - 0.26, 0.32, {
      size: 8.4,
      color: colors.muted,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
    if (itemIndex < items.length - 1) {
      addArrow(pptx, slide, x + boxW + 0.06, 3.58, x + boxW + gap - 0.08, 3.58, colors.muted, 1);
    }
  });
  if (slideSpec.body) {
    addText(slide, slideSpec.body, 1.15, 5.5, 10.8, 0.4, {
      size: 13,
      bold: true,
      color: colors.green,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
  }
  addFooter(slide, index, colors, font);
  return slide;
}

function metricRail(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  addTitleBlock(pptx, slide, slideSpec, colors, font);
  const items = normalizeItems(slideSpec.items).slice(0, 5);
  const count = Math.max(items.length, 1);
  const panelW = Math.min(2.35, 11.2 / count);
  const gap = count > 1 ? (11.2 - panelW * count) / (count - 1) : 0;
  items.forEach((item, itemIndex) => {
    const x = 0.95 + itemIndex * (panelW + gap);
    addPanel(pptx, slide, x, 2.35, panelW, 3.05, colors, { fill: colors.white });
    addText(slide, item.value || item.label || "", x + 0.12, 2.92, panelW - 0.24, 0.48, {
      size: 27,
      bold: true,
      color: [colors.green, colors.blue, colors.amber, colors.red, colors.ink][itemIndex % 5],
      margin: 0,
      align: "center",
      fontFace: font.head,
    });
    addText(slide, item.label || item.text || "", x + 0.18, 3.68, panelW - 0.36, 0.34, {
      size: 11.5,
      bold: true,
      color: colors.ink,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
    addText(slide, item.text || item.note || "", x + 0.22, 4.22, panelW - 0.44, 0.62, {
      size: 9.2,
      color: colors.muted,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
  });
  addFooter(slide, index, colors, font);
  return slide;
}

function timeline(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  addTitleBlock(pptx, slide, slideSpec, colors, font);
  const items = normalizeItems(slideSpec.items).slice(0, 6);
  addRule(pptx, slide, 1.05, 3.55, 11.0, colors.hair, 1.2);
  items.forEach((item, itemIndex) => {
    const x = 1.05 + itemIndex * (11.0 / Math.max(items.length - 1, 1));
    slide.addShape(pptx.ShapeType.ellipse, {
      x: x - 0.08,
      y: 3.46,
      w: 0.18,
      h: 0.18,
      fill: { color: [colors.green, colors.blue, colors.amber][itemIndex % 3] },
      line: { color: [colors.green, colors.blue, colors.amber][itemIndex % 3] },
    });
    addText(slide, item.label || item.date || "", x - 0.55, 3.0, 1.1, 0.22, {
      size: 10,
      bold: true,
      color: colors.ink,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
    addText(slide, item.text || item.body || "", x - 0.75, 3.85, 1.5, 0.55, {
      size: 8.8,
      color: colors.muted,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
  });
  addFooter(slide, index, colors, font);
  return slide;
}

function tableSlide(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  addTitleBlock(pptx, slide, slideSpec, colors, font);
  const headers = slideSpec.headers || ["Item", "Detail", "Signal"];
  const rows = Array.isArray(slideSpec.rows) ? slideSpec.rows : normalizeItems(slideSpec.items);
  const x = 0.9;
  const y = 2.1;
  const w = 11.55;
  const rowH = 0.44;
  const colW = w / headers.length;
  headers.forEach((header, col) => {
    slide.addShape(pptx.ShapeType.rect, {
      x: x + col * colW,
      y,
      w: colW,
      h: rowH,
      fill: { color: colors.dark },
      line: { color: colors.dark },
    });
    addText(slide, header, x + col * colW + 0.08, y + 0.13, colW - 0.16, 0.12, {
      size: 8.5,
      bold: true,
      color: colors.white,
      margin: 0,
      fontFace: font.body,
    });
  });
  rows.slice(0, 9).forEach((row, rowIndex) => {
    const cells = Array.isArray(row)
      ? row
      : [row.label || row.value || "", row.text || row.body || "", row.signal || row.note || ""];
    const rowY = y + rowH * (rowIndex + 1);
    headers.forEach((_, col) => {
      const fill = rowIndex % 2 ? colors.paper : colors.white;
      slide.addShape(pptx.ShapeType.rect, {
        x: x + col * colW,
        y: rowY,
        w: colW,
        h: rowH,
        fill: { color: fill },
        line: { color: colors.hair, transparency: 15 },
      });
      addText(slide, cells[col] || "", x + col * colW + 0.08, rowY + 0.12, colW - 0.16, 0.15, {
        size: 8.2,
        color: colors.ink,
        margin: 0,
        fontFace: font.body,
      });
    });
  });
  addFooter(slide, index, colors, font);
  return slide;
}

function quoteSlide(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors, "dark");
  addText(slide, slideSpec.claim || slideSpec.body || "Quote", 1.05, 1.35, 10.8, 2.1, {
    size: 30,
    bold: true,
    color: colors.white,
    margin: 0,
    fontFace: font.head,
  });
  addRule(pptx, slide, 1.08, 4.45, 1.45, colors.amber, 2);
  addText(slide, slideSpec.support || slideSpec.attribution || "", 1.08, 4.78, 7.6, 0.45, {
    size: 12,
    color: "DDE8E0",
    margin: 0,
    fontFace: font.body,
  });
  addFooter(slide, index, colors, font, true);
  return slide;
}

function sectionSlide(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors, "dark");
  addKicker(pptx, slide, slideSpec.kicker || `SECTION ${index}`, 0.82, 1.1, colors, font);
  addText(slide, slideSpec.claim || slideSpec.title || "Section", 0.82, 1.68, 9.5, 1.0, {
    size: 34,
    bold: true,
    color: colors.white,
    margin: 0,
    fontFace: font.head,
  });
  addText(slide, slideSpec.support || slideSpec.body || "", 0.85, 3.0, 7.5, 0.55, {
    size: 13,
    color: "DDE8E0",
    margin: 0,
    fontFace: font.body,
  });
  addFooter(slide, index, colors, font, true);
  return slide;
}

function imageLedSlide(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors, "dark");
  const images = normalizeImages(slideSpec);
  if (images.length) {
    addImage(pptx, slide, images[0], 0, 0, W, H, colors, font, {
      frame: false,
      caption: false,
      fit: "cover",
    });
    slide.addShape(pptx.ShapeType.rect, {
      x: 0,
      y: 0,
      w: W,
      h: H,
      fill: { color: colors.black, transparency: 48 },
      line: { color: colors.black, transparency: 100 },
    });
  }
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 0.18,
    h: H,
    fill: { color: colors.red },
    line: { color: colors.red },
  });
  addText(slide, slideSpec.kicker || slideSpec.type || "STORY", 0.72, 0.72, 3.2, 0.2, {
    size: 9.5,
    bold: true,
    color: colors.amber,
    margin: 0,
    fontFace: font.body,
  });
  addText(slide, slideSpec.claim || slideSpec.title || "Untitled slide", 0.72, 1.12, 7.1, 1.25, {
    size: 34,
    bold: true,
    color: colors.white,
    margin: 0,
    fontFace: font.head,
  });
  if (slideSpec.support || slideSpec.body) {
    addText(slide, slideSpec.support || slideSpec.body, 0.75, 2.72, 6.2, 0.55, {
      size: 15,
      bold: true,
      color: "F3E6B7",
      margin: 0,
      fontFace: font.body,
    });
  }
  const items = normalizeItems(slideSpec.items).slice(0, 5);
  items.forEach((item, itemIndex) => {
    addPanel(pptx, slide, 0.75 + itemIndex * 1.42, 6.38, 1.16, 0.36, colors, {
      fill: colors.black,
      line: colors.white,
      lineTransparency: 70,
    });
    addText(slide, item.label || item.text || item.value || "", 0.84 + itemIndex * 1.42, 6.49, 0.98, 0.11, {
      size: 8,
      bold: true,
      color: colors.white,
      margin: 0,
      align: "center",
      fontFace: font.body,
    });
  });
  addText(slide, String(index).padStart(2, "0"), 12.15, 6.92, 0.42, 0.12, {
    size: 8,
    bold: true,
    color: colors.white,
    margin: 0,
    align: "right",
    fontFace: font.body,
  });
  return slide;
}

function imageGridSlide(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  addTitleBlock(pptx, slide, slideSpec, colors, font);
  const images = normalizeImages(slideSpec).slice(0, 4);
  if (!images.length) return genericSlide(pptx, deck, slideSpec, colors, font, index);
  const items = normalizeItems(slideSpec.items).slice(0, images.length);
  const slotsByCount = {
    1: [
      { x: 0.9, y: 2.02, w: 10.55, h: 4.0 },
    ],
    2: [
      { x: 0.9, y: 2.02, w: 5.25, h: 3.82 },
      { x: 6.38, y: 2.02, w: 5.25, h: 3.82 },
    ],
    3: [
      { x: 0.9, y: 2.02, w: 5.72, h: 3.94 },
      { x: 6.88, y: 2.02, w: 4.78, h: 1.86 },
      { x: 6.88, y: 4.10, w: 4.78, h: 1.86 },
    ],
    4: [
      { x: 0.9, y: 2.02, w: 5.0, h: 2.04 },
      { x: 6.14, y: 2.02, w: 5.0, h: 2.04 },
      { x: 0.9, y: 4.55, w: 5.0, h: 1.45 },
      { x: 6.14, y: 4.55, w: 5.0, h: 1.45 },
    ],
  };
  const slots = slotsByCount[images.length] || slotsByCount[4];
  images.forEach((image, imageIndex) => {
    const slot = slots[imageIndex];
    addImage(pptx, slide, image, slot.x, slot.y, slot.w, slot.h, colors, font, {
      caption: false,
      fit: image.fit || "cover",
    });
    const label = String(items[imageIndex]?.label || "").trim();
    if (label) {
      slide.addShape(pptx.ShapeType.roundRect, {
        x: slot.x + 0.16,
        y: slot.y + 0.14,
        w: Math.min(2.35, slot.w - 0.32),
        h: 0.32,
        rectRadius: 0.04,
        fill: { color: imageIndex % 2 === 0 ? colors.accent : colors.ink, transparency: 8 },
        line: { color: colors.white, transparency: 100 },
      });
      addText(slide, label, slot.x + 0.28, slot.y + 0.245, Math.min(2.1, slot.w - 0.56), 0.11, {
        size: 9.5,
        bold: true,
        color: colors.white,
        margin: 0,
        breakLine: false,
        fontFace: font.body,
      });
    }
  });
  addFooter(slide, index, colors, font);
  return slide;
}

function genericSlide(pptx, deck, slideSpec, colors, font, index) {
  const slide = deck.addSlide();
  addBg(pptx, slide, colors);
  addTitleBlock(pptx, slide, slideSpec, colors, font);
  const images = normalizeImages(slideSpec);
  if (images.length) {
    addImage(pptx, slide, images[0], 0.9, 2.04, 4.9, 3.6, colors, font, {
      fit: images[0].fit || "cover",
    });
  }
  const items = normalizeItems(slideSpec.items).slice(0, 6);
  items.forEach((item, itemIndex) => {
    const x = images.length ? 6.35 : 0.9 + (itemIndex % 2) * 5.95;
    const y = images.length ? 2.05 + itemIndex * 1.02 : 2.05 + Math.floor(itemIndex / 2) * 1.4;
    const panelW = images.length ? 5.65 : 5.2;
    addPanel(pptx, slide, x, y, panelW, 0.98, colors, { fill: colors.white });
    addText(slide, item.label || item.value || "", x + 0.25, y + 0.2, panelW - 0.65, 0.18, {
      size: 12.5,
      bold: true,
      color: [colors.green, colors.blue, colors.amber][itemIndex % 3],
      margin: 0,
      fontFace: font.body,
    });
    addText(slide, item.text || item.note || "", x + 0.25, y + 0.52, panelW - 0.65, 0.28, {
      size: 9.5,
      color: colors.muted,
      margin: 0,
      fontFace: font.body,
    });
  });
  if (!items.length && slideSpec.body) {
    addText(slide, slideSpec.body, images.length ? 6.35 : 1.0, 2.35, images.length ? 5.2 : 10.6, 1.2, {
      size: 16,
      color: colors.ink,
      margin: 0,
      fontFace: font.body,
    });
  }
  addFooter(slide, index, colors, font);
  return slide;
}

function createDeck(pptxgen, spec) {
  const pptx = new pptxgen();
  const font = fontFromSpec(spec);
  pptx.defineLayout({ name: "FERRYMAN_WIDE", width: W, height: H });
  pptx.layout = "FERRYMAN_WIDE";
  pptx.author = spec.author || "Ferryman";
  pptx.company = spec.company || "Ferryman";
  pptx.subject = spec.source_summary || spec.subtitle || spec.title || "Presentation";
  pptx.title = spec.title || "Presentation";
  pptx.lang = font.lang;
  pptx.theme = {
    headFontFace: font.head,
    bodyFontFace: font.body,
    lang: font.lang,
  };
  return pptx;
}

function renderSlide(pptxgen, deck, spec, slideSpec, colors, font, index) {
  const layout = String(slideSpec.layout || slideSpec.type || "generic").toLowerCase();
  if (layout.includes("full-bleed-photo") || layout.includes("photo-caption") || layout.includes("classroom-takeaway")) {
    return imageLedSlide(pptxgen, deck, slideSpec, colors, font, index);
  }
  if (layout.includes("image-grid")) return imageGridSlide(pptxgen, deck, slideSpec, colors, font, index);
  if (layout.includes("cover")) return coverProcess(pptxgen, deck, slideSpec, colors, font, index);
  if (layout.includes("big-claim") || layout.includes("diagnosis") || slideSpec.type === "thesis") {
    return bigClaim(pptxgen, deck, slideSpec, colors, font, index);
  }
  if (layout.includes("two-column") || layout.includes("compare") || slideSpec.type === "comparison") {
    return twoColumnCompare(pptxgen, deck, slideSpec, colors, font, index);
  }
  if (layout.includes("flow") || layout.includes("phase")) return horizontalFlow(pptxgen, deck, slideSpec, colors, font, index);
  if (layout.includes("metric")) return metricRail(pptxgen, deck, slideSpec, colors, font, index);
  if (layout.includes("timeline")) return timeline(pptxgen, deck, slideSpec, colors, font, index);
  if (layout.includes("table") || slideSpec.type === "table") return tableSlide(pptxgen, deck, slideSpec, colors, font, index);
  if (layout.includes("quote") || slideSpec.type === "quote") return quoteSlide(pptxgen, deck, slideSpec, colors, font, index);
  if (layout.includes("section") || slideSpec.type === "section") return sectionSlide(pptxgen, deck, slideSpec, colors, font, index);
  return genericSlide(pptxgen, deck, slideSpec, colors, font, index);
}

function validateSpecForBuild(spec) {
  const errors = [];
  if (!spec || typeof spec !== "object") errors.push("Spec must be a JSON object.");
  if (!spec.title) errors.push("Spec is missing title.");
  if (!Array.isArray(spec.slides) || spec.slides.length === 0) {
    errors.push("Spec must include a non-empty slides array.");
  }
  return errors;
}

function buildDeckFromSpec(pptxgen, spec) {
  const errors = validateSpecForBuild(spec);
  if (errors.length) {
    const error = new Error(`Invalid deck spec:\n${errors.join("\n")}`);
    error.errors = errors;
    throw error;
  }
  const colors = themeFromSpec(spec);
  const font = fontFromSpec(spec);
  const deck = createDeck(pptxgen, spec);
  spec.slides.forEach((slideSpec, idx) => {
    renderSlide(deck, deck, spec, slideSpec, colors, font, idx + 1);
  });
  return deck;
}

function defaultOutputForSpec(specPath, spec) {
  const dir = path.dirname(path.resolve(specPath));
  return path.join(dir, "output", `${slugify(spec.title, "presentation")}.pptx`);
}

module.exports = {
  W,
  H,
  DEFAULT_THEME,
  readJson,
  slugify,
  hasImage,
  themeFromSpec,
  fontFromSpec,
  createDeck,
  resolveInputPath,
  normalizeImageFit,
  validateSpecForBuild,
  buildDeckFromSpec,
  defaultOutputForSpec,
};
