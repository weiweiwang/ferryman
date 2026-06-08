#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const { DEFAULT_THEME, H, W, fontFromSpec, readJson, slugify, themeFromSpec } = require("./pptx_helpers");

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
    "  node scripts/build_html_deck.js --spec <deck-spec.json> --out-dir <html-dir> [--manifest <manifest.json>]",
    "",
    "Generates controlled per-slide HTML for the hybrid PPTX pipeline.",
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

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cssHex(value, fallback) {
  const raw = String(value || fallback || "").replace(/^#/, "");
  return /^[0-9a-fA-F]{6}$/.test(raw) ? `#${raw}` : `#${DEFAULT_THEME.paper}`;
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

function imageSrc(imageSpec, htmlDir) {
  if (!imageSpec || typeof imageSpec !== "object") return "";
  const raw = imageSpec.path || imageSpec.src;
  if (!raw) return "";
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(String(raw))) {
    throw new Error(`Image path must be a workspace file path, not a URL: ${raw}`);
  }
  const resolved = path.isAbsolute(raw) ? path.resolve(raw) : path.resolve(process.cwd(), raw);
  const relativeToWorkspace = path.relative(process.cwd(), resolved);
  if (relativeToWorkspace.startsWith("..") || path.isAbsolute(relativeToWorkspace)) {
    throw new Error(`Image path escapes workspace: ${raw}`);
  }
  const relativeToHtml = path.relative(htmlDir, resolved).split(path.sep).join("/");
  return encodeURI(relativeToHtml);
}

function dataAttrs(type, extra = {}) {
  const attrs = [`data-pptx="${escapeHtml(type)}"`];
  for (const [key, value] of Object.entries(extra)) {
    if (value === undefined || value === null || value === "") continue;
    attrs.push(`data-${key}="${escapeHtml(value)}"`);
  }
  return attrs.join(" ");
}

function style(obj) {
  return Object.entries(obj)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${key}:${value}`)
    .join(";");
}

function textBox(type, text, x, y, w, h, extraStyle = {}, attrs = {}) {
  return `<div class="box ${type}" ${dataAttrs(type, attrs)} style="${style({
    left: `${x}px`,
    top: `${y}px`,
    width: `${w}px`,
    height: `${h}px`,
    ...extraStyle,
  })}">${escapeHtml(text)}</div>`;
}

function panel(x, y, w, h, cls = "panel", attrs = {}) {
  return `<div class="${cls}" ${dataAttrs("shape", { shape: "roundRect", ...attrs })} style="${style({
    left: `${x}px`,
    top: `${y}px`,
    width: `${w}px`,
    height: `${h}px`,
  })}"></div>`;
}

function imageBox(imageSpec, htmlDir, x, y, w, h, cls = "image", fit = "cover") {
  const src = imageSrc(imageSpec, htmlDir);
  const alt = escapeHtml(imageSpec.alt || imageSpec.caption || "");
  const rawPath = escapeHtml(imageSpec.path || imageSpec.src || "");
  return `<img class="${cls}" ${dataAttrs("image", {
    path: rawPath,
    fit: imageSpec.fit || fit,
    alt,
  })} src="${src}" alt="${alt}" style="${style({
    left: `${x}px`,
    top: `${y}px`,
    width: `${w}px`,
    height: `${h}px`,
    "object-fit": imageSpec.fit || fit,
  })}">`;
}

function addKicker(slide) {
  return textBox("kicker", slide.kicker || slide.type || "PRESENTATION", 72, 46, 320, 22, {
    "font-size": "13px",
    "font-weight": "700",
    "letter-spacing": "0",
    "text-transform": "uppercase",
  });
}

function title(slide, x = 72, y = 82, w = 960, h = 76, dark = false) {
  return textBox("title", slide.claim || slide.title || "Untitled slide", x, y, w, h, {
    "font-size": "31px",
    "line-height": "1.08",
    "font-weight": "800",
    color: dark ? "var(--white)" : "var(--ink)",
  });
}

function support(slide, x = 74, y = 160, w = 880, h = 42, dark = false) {
  if (!slide.support) return "";
  return textBox("body", slide.support, x, y, w, h, {
    "font-size": "15px",
    "line-height": "1.35",
    color: dark ? "var(--pale)" : "var(--muted)",
  });
}

function templateName(spec) {
  const theme = spec && typeof spec.theme === "object" ? spec.theme : {};
  return String(spec.visual_style || spec.template || theme.template || theme.visual_style || "").toLowerCase();
}

function isPremiumEditorial(spec) {
  return ["premium-editorial", "premium-briefing", "editorial-briefing"].includes(templateName(spec));
}

function isScienceStorybook(spec) {
  return ["science-storybook", "science-documentary", "museum-science", "earth-storybook"].includes(templateName(spec));
}

function firstImage(slide) {
  return normalizeImages(slide)[0];
}

function itemLabel(item, fallback = "") {
  return item.label || item.name || item.value || item.date || fallback;
}

function itemBody(item) {
  return item.text || item.body || item.note || item.description || "";
}

function premiumKicker(slide, dark = true) {
  return textBox("kicker", slide.kicker || slide.type || "BRIEFING", 82, 54, 440, 22, {
    color: dark ? "var(--premium-copper)" : "var(--premium-accent)",
    "font-size": "12px",
    "font-weight": "850",
    "letter-spacing": "0",
    "text-transform": "uppercase",
  });
}

function premiumFooter(slide, dark = true) {
  return [
    `<div class="premium-footer-rule" data-raster="true"></div>`,
    textBox("footer", String(slide.number || "").padStart(2, "0"), 1148, 652, 48, 18, {
      color: dark ? "rgba(244,238,226,.72)" : "rgba(21,27,32,.55)",
      "font-size": "11px",
      "text-align": "right",
    }),
  ].join("\n");
}

function premiumMicroStats(slide, x, y, dark = true) {
  const items = normalizeItems(slide.items).slice(0, 3);
  if (!items.length) return "";
  return items.map((item, idx) => {
    const cardX = x + idx * 176;
    return [
      `<div class="premium-chip ${dark ? "dark-chip" : "light-chip"}" data-raster="true" style="left:${cardX}px;top:${y}px;width:154px;height:68px"></div>`,
      textBox("label", itemLabel(item, `Signal ${idx + 1}`), cardX + 18, y + 14, 124, 16, {
        color: dark ? "var(--premium-copper)" : "var(--premium-accent)",
        "font-size": "10px",
        "font-weight": "850",
      }),
      textBox("body", itemBody(item) || item.value || itemLabel(item), cardX + 18, y + 34, 120, 22, {
        color: dark ? "var(--premium-cream)" : "var(--premium-ink)",
        "font-size": "15px",
        "font-weight": "800",
      }),
    ].join("\n");
  }).join("\n");
}

function premiumCoverSlide(slide, htmlDir) {
  const image = firstImage(slide);
  return [
    `<div class="premium-bg premium-bg-dark" data-raster="true"></div>`,
    `<div class="premium-left-rule" data-raster="true"></div>`,
    premiumKicker(slide, true),
    textBox("title", slide.claim || slide.title || "Untitled briefing", 82, 116, image ? 506 : 780, 168, {
      color: "var(--premium-cream)",
      "font-size": "44px",
      "line-height": "1.04",
      "font-weight": "900",
    }),
    textBox("body", slide.body || slide.support || "", 86, 330, image ? 488 : 720, 74, {
      color: "rgba(244,238,226,.78)",
      "font-size": "17px",
      "line-height": "1.45",
      "font-weight": "520",
    }),
    `<div class="premium-gold-rule" data-raster="true" style="left:86px;top:452px;width:178px"></div>`,
    image ? imageBox(image, htmlDir, 660, 38, 540, 628, "premium-cover-image", image.fit || "cover") : `<div class="premium-abstract-panel" data-raster="true"></div>`,
    image ? `<div class="premium-photo-vignette" data-raster="true"></div>` : "",
    premiumMicroStats(slide, 84, 560, true),
    premiumFooter(slide, true),
  ].join("\n");
}

function premiumInsightSlide(slide, htmlDir) {
  const image = firstImage(slide);
  const items = normalizeItems(slide.items).slice(0, 3);
  return [
    `<div class="premium-bg premium-bg-paper" data-raster="true"></div>`,
    premiumKicker(slide, false),
    textBox("title", slide.claim || slide.title || "Untitled insight", 82, 88, 820, 92, {
      color: "var(--premium-ink)",
      "font-size": "34px",
      "line-height": "1.08",
      "font-weight": "900",
    }),
    textBox("body", slide.support || slide.body || "", 84, 186, 660, 38, {
      color: "var(--premium-muted)",
      "font-size": "14px",
      "line-height": "1.38",
    }),
    image ? imageBox(image, htmlDir, 74, 268, 478, 326, "premium-photo", image.fit || "cover") : `<div class="premium-abstract-small" data-raster="true"></div>`,
    `<div class="premium-image-caption-bar" data-raster="true"></div>`,
    items.map((item, idx) => {
      const y = 266 + idx * 106;
      return [
        `<div class="premium-insight-card" data-raster="true" style="left:628px;top:${y}px"></div>`,
        textBox("label", itemLabel(item, `Insight ${idx + 1}`), 656, y + 20, 420, 22, {
          color: "var(--premium-accent)",
          "font-size": "15px",
          "font-weight": "900",
        }),
        textBox("body", itemBody(item), 656, y + 48, 388, 32, {
          color: "var(--premium-ink)",
          "font-size": "13px",
          "line-height": "1.34",
        }),
      ].join("\n");
    }).join("\n"),
    premiumFooter(slide, false),
  ].join("\n");
}

function premiumMetricSlide(slide) {
  const items = normalizeItems(slide.items).slice(0, 4);
  return [
    `<div class="premium-bg premium-bg-dark" data-raster="true"></div>`,
    premiumKicker(slide, true),
    textBox("title", slide.claim || slide.title || "Untitled metrics", 82, 90, 900, 88, {
      color: "var(--premium-cream)",
      "font-size": "35px",
      "line-height": "1.08",
      "font-weight": "900",
    }),
    textBox("body", slide.support || slide.body || "", 84, 184, 760, 34, {
      color: "rgba(244,238,226,.7)",
      "font-size": "14px",
      "line-height": "1.35",
    }),
    items.map((item, idx) => {
      const x = 78 + idx * 292;
      const value = item.value || item.metric || itemLabel(item, "");
      return [
        `<div class="premium-metric-card" data-raster="true" style="left:${x}px;top:286px"></div>`,
        textBox("metric", value, x + 26, 322, 224, 62, {
          color: idx % 2 ? "var(--premium-sky)" : "var(--premium-copper)",
          "font-size": value.length > 8 ? "38px" : "48px",
          "font-weight": "950",
          "line-height": "1",
        }),
        textBox("label", item.label || item.name || "", x + 28, 406, 218, 24, {
          color: "var(--premium-cream)",
          "font-size": "17px",
          "font-weight": "850",
        }),
        textBox("body", itemBody(item), x + 28, 448, 214, 70, {
          color: "rgba(244,238,226,.68)",
          "font-size": "12px",
          "line-height": "1.35",
        }),
        `<div class="premium-meter" data-raster="true" style="left:${x + 28}px;top:548px;width:${120 + idx * 28}px"></div>`,
      ].join("\n");
    }).join("\n"),
    premiumFooter(slide, true),
  ].join("\n");
}

function premiumTimelineSlide(slide) {
  const items = normalizeItems(slide.items).slice(0, 5);
  return [
    `<div class="premium-bg premium-bg-paper" data-raster="true"></div>`,
    premiumKicker(slide, false),
    textBox("title", slide.claim || slide.title || "Untitled timeline", 82, 90, 920, 84, {
      color: "var(--premium-ink)",
      "font-size": "34px",
      "line-height": "1.08",
      "font-weight": "900",
    }),
    textBox("body", slide.support || slide.body || "", 84, 184, 780, 34, {
      color: "var(--premium-muted)",
      "font-size": "14px",
      "line-height": "1.35",
    }),
    `<div class="premium-timeline-rail" data-raster="true"></div>`,
    items.map((item, idx) => {
      const x = 100 + idx * (1040 / Math.max(items.length - 1, 1));
      const high = idx % 2 === 0;
      const y = high ? 286 : 414;
      return [
        `<div class="premium-timeline-node" data-raster="true" style="left:${x - 7}px"></div>`,
        `<div class="premium-timeline-card" data-raster="true" style="left:${x - 82}px;top:${y}px"></div>`,
        textBox("label", itemLabel(item, `T${idx + 1}`), x - 60, y + 20, 120, 22, {
          color: "var(--premium-accent)",
          "font-size": "14px",
          "font-weight": "900",
          "text-align": "center",
        }),
        textBox("body", itemBody(item), x - 64, y + 52, 128, 56, {
          color: "var(--premium-ink)",
          "font-size": "11px",
          "line-height": "1.32",
          "text-align": "center",
        }),
      ].join("\n");
    }).join("\n"),
    premiumFooter(slide, false),
  ].join("\n");
}

function premiumCloseSlide(slide, htmlDir) {
  const image = firstImage(slide);
  const items = normalizeItems(slide.items).slice(0, 3);
  return [
    `<div class="premium-bg premium-bg-dark" data-raster="true"></div>`,
    image ? imageBox(image, htmlDir, 0, 0, 420, 720, "premium-side-image", image.fit || "cover") : `<div class="premium-side-abstract" data-raster="true"></div>`,
    `<div class="premium-side-shade" data-raster="true"></div>`,
    premiumKicker(slide, true),
    textBox("title", slide.claim || slide.title || "Untitled close", 500, 118, 620, 128, {
      color: "var(--premium-cream)",
      "font-size": "40px",
      "line-height": "1.06",
      "font-weight": "900",
    }),
    textBox("body", slide.support || slide.body || "", 504, 292, 560, 58, {
      color: "rgba(244,238,226,.72)",
      "font-size": "16px",
      "line-height": "1.42",
    }),
    items.map((item, idx) => {
      const y = 418 + idx * 72;
      return [
        `<div class="premium-close-dot" data-raster="true" style="left:506px;top:${y + 6}px"></div>`,
        textBox("label", itemLabel(item, `Takeaway ${idx + 1}`), 540, y, 420, 24, {
          color: "var(--premium-copper)",
          "font-size": "15px",
          "font-weight": "900",
        }),
        textBox("body", itemBody(item), 540, y + 26, 520, 28, {
          color: "var(--premium-cream)",
          "font-size": "13px",
          "line-height": "1.35",
        }),
      ].join("\n");
    }).join("\n"),
    premiumFooter(slide, true),
  ].join("\n");
}

function premiumSlideBody(slide, htmlDir) {
  const layout = String(slide.layout || slide.type || "generic").toLowerCase();
  if (layout.includes("cover")) return premiumCoverSlide(slide, htmlDir);
  if (layout.includes("metric") || layout.includes("signal")) return premiumMetricSlide(slide);
  if (layout.includes("timeline") || layout.includes("roadmap")) return premiumTimelineSlide(slide);
  if (layout.includes("close") || layout.includes("takeaway") || layout.includes("summary")) return premiumCloseSlide(slide, htmlDir);
  return premiumInsightSlide(slide, htmlDir);
}

function scienceIsDark(slide) {
  const layout = String(slide.layout || slide.type || "").toLowerCase();
  return !layout.match(/time-river|scale-day|mechanism-light|evidence-triptych|field-guide/);
}

function scienceKicker(slide, dark = true) {
  return textBox("kicker", slide.kicker || slide.type || "EARTH STORY", 66, 44, 420, 22, {
    color: dark ? "var(--science-ember)" : "var(--science-deep)",
    "font-size": "12px",
    "font-weight": "900",
    "text-transform": "uppercase",
  });
}

function scienceFooter(slide, dark = true) {
  return [
    `<div class="science-footer-rule" data-raster="true"></div>`,
    textBox("footer", String(slide.number || "").padStart(2, "0"), 1160, 656, 48, 18, {
      color: dark ? "rgba(242,232,212,.68)" : "rgba(28,38,43,.52)",
      "font-size": "10px",
      "text-align": "right",
    }),
  ].join("\n");
}

function scienceBg(dark = true) {
  return dark
    ? [
      `<div class="science-bg science-bg-deep" data-raster="true"></div>`,
      `<div class="science-starfield" data-raster="true"></div>`,
      `<div class="science-haze" data-raster="true"></div>`,
    ].join("\n")
    : [
      `<div class="science-bg science-bg-paper" data-raster="true"></div>`,
      `<div class="science-paper-grain" data-raster="true"></div>`,
    ].join("\n");
}

function scienceAbstractOrb(x, y, size, cls = "science-orb") {
  return [
    `<div class="${cls}" data-raster="true" style="left:${x}px;top:${y}px;width:${size}px;height:${size}px"></div>`,
    `<div class="science-orb-shadow" data-raster="true" style="left:${x + size * 0.16}px;top:${y + size * 0.18}px;width:${size * 0.8}px;height:${size * 0.8}px"></div>`,
  ].join("\n");
}

function scienceCoverSlide(slide, htmlDir) {
  const image = firstImage(slide);
  const items = normalizeItems(slide.items).slice(0, 4);
  return [
    scienceBg(true),
    image ? imageBox(image, htmlDir, 638, 0, 642, 720, "science-cover-image", image.fit || "cover") : scienceAbstractOrb(690, 48, 520, "science-earth-orb"),
    `<div class="science-cover-shade" data-raster="true"></div>`,
    `<div class="science-left-rail" data-raster="true"></div>`,
    scienceKicker(slide, true),
    textBox("title", slide.claim || slide.title || "Earth story", 66, 110, 580, 176, {
      color: "var(--science-cream)",
      "font-size": "50px",
      "line-height": "1.02",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 70, 326, 502, 76, {
      color: "rgba(242,232,212,.76)",
      "font-size": "16px",
      "line-height": "1.45",
    }),
    `<div class="science-long-rule" data-raster="true" style="left:70px;top:442px;width:218px"></div>`,
    items.map((item, idx) => {
      const x = 70 + idx * 134;
      return [
        `<div class="science-seal" data-raster="true" style="left:${x}px;top:568px"></div>`,
        textBox("label", itemLabel(item, `Stage ${idx + 1}`), x + 12, 586, 86, 18, {
          color: "var(--science-cream)",
          "font-size": "11px",
          "font-weight": "900",
          "text-align": "center",
        }),
      ].join("\n");
    }).join("\n"),
    scienceFooter(slide, true),
  ].join("\n");
}

function scienceTimeRiverSlide(slide) {
  const items = normalizeItems(slide.items).slice(0, 7);
  return [
    scienceBg(false),
    scienceKicker(slide, false),
    textBox("title", slide.claim || slide.title || "A time river", 66, 84, 940, 82, {
      color: "var(--science-ink)",
      "font-size": "36px",
      "line-height": "1.08",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 68, 174, 780, 40, {
      color: "var(--science-muted)",
      "font-size": "14px",
      "line-height": "1.36",
    }),
    `<div class="science-river" data-raster="true"></div>`,
    `<div class="science-river-glow" data-raster="true"></div>`,
    items.map((item, idx) => {
      const x = 92 + idx * (1080 / Math.max(items.length - 1, 1));
      const y = idx % 2 === 0 ? 300 : 438;
      return [
        `<div class="science-river-dot" data-raster="true" style="left:${x - 8}px"></div>`,
        `<div class="science-river-card" data-raster="true" style="left:${x - 76}px;top:${y}px"></div>`,
        textBox("label", itemLabel(item, ""), x - 60, y + 18, 120, 22, {
          color: "var(--science-deep)",
          "font-size": "14px",
          "font-weight": "950",
          "text-align": "center",
        }),
        textBox("body", itemBody(item), x - 64, y + 48, 128, 52, {
          color: "var(--science-muted)",
          "font-size": "11px",
          "line-height": "1.28",
          "text-align": "center",
        }),
      ].join("\n");
    }).join("\n"),
    scienceFooter(slide, false),
  ].join("\n");
}

function scienceScaleDaySlide(slide) {
  const items = normalizeItems(slide.items).slice(0, 4);
  return [
    scienceBg(true),
    scienceKicker(slide, true),
    textBox("title", slide.claim || slide.title || "Scale shift", 66, 88, 720, 88, {
      color: "var(--science-cream)",
      "font-size": "39px",
      "line-height": "1.06",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 68, 186, 650, 40, {
      color: "rgba(242,232,212,.72)",
      "font-size": "14px",
      "line-height": "1.36",
    }),
    `<div class="science-clock" data-raster="true"></div>`,
    `<div class="science-clock-hand" data-raster="true"></div>`,
    items.map((item, idx) => {
      const x = idx % 2 === 0 ? 646 : 914;
      const y = 264 + Math.floor(idx / 2) * 160;
      return [
        `<div class="science-night-card" data-raster="true" style="left:${x}px;top:${y}px"></div>`,
        textBox("label", itemLabel(item, ""), x + 24, y + 22, 200, 22, {
          color: "var(--science-ember)",
          "font-size": "16px",
          "font-weight": "950",
        }),
        textBox("body", itemBody(item), x + 24, y + 54, 206, 54, {
          color: "var(--science-cream)",
          "font-size": "12px",
          "line-height": "1.34",
        }),
      ].join("\n");
    }).join("\n"),
    scienceFooter(slide, true),
  ].join("\n");
}

function scienceChapterSlide(slide, htmlDir) {
  const image = firstImage(slide);
  const items = normalizeItems(slide.items).slice(0, 3);
  return [
    scienceBg(true),
    image ? imageBox(image, htmlDir, 678, 72, 514, 574, "science-chapter-image", image.fit || "cover") : scienceAbstractOrb(748, 106, 410, "science-magma-orb"),
    `<div class="science-image-frame" data-raster="true" style="left:678px;top:72px;width:514px;height:574px"></div>`,
    scienceKicker(slide, true),
    textBox("metric", slide.epoch || slide.value || itemLabel(items[0] || {}, "46亿年"), 66, 102, 508, 84, {
      color: "var(--science-ember)",
      "font-size": "52px",
      "font-weight": "950",
      "line-height": "1",
    }),
    textBox("title", slide.claim || slide.title || "Chapter", 68, 210, 540, 110, {
      color: "var(--science-cream)",
      "font-size": "34px",
      "line-height": "1.08",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 70, 346, 510, 60, {
      color: "rgba(242,232,212,.72)",
      "font-size": "14px",
      "line-height": "1.38",
    }),
    items.slice(0, 2).map((item, idx) => {
      const y = 460 + idx * 74;
      return [
        `<div class="science-mini-card" data-raster="true" style="left:72px;top:${y}px"></div>`,
        textBox("label", itemLabel(item, `Key ${idx + 1}`), 96, y + 14, 430, 18, {
          color: "var(--science-ember)",
          "font-size": "13px",
          "font-weight": "950",
        }),
        textBox("body", itemBody(item), 96, y + 36, 428, 24, {
          color: "var(--science-cream)",
          "font-size": "12px",
          "line-height": "1.32",
        }),
      ].join("\n");
    }).join("\n"),
    scienceFooter(slide, true),
  ].join("\n");
}

function scienceMechanismSlide(slide, htmlDir) {
  const image = firstImage(slide);
  const items = normalizeItems(slide.items).slice(0, 4);
  return [
    scienceBg(false),
    scienceKicker(slide, false),
    textBox("title", slide.claim || slide.title || "Mechanism", 66, 78, 790, 86, {
      color: "var(--science-ink)",
      "font-size": "35px",
      "line-height": "1.08",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 68, 170, 720, 38, {
      color: "var(--science-muted)",
      "font-size": "14px",
      "line-height": "1.36",
    }),
    image ? imageBox(image, htmlDir, 72, 248, 494, 344, "science-field-image", image.fit || "cover") : `<div class="science-diagram-field" data-raster="true"></div>`,
    `<div class="science-image-frame light-frame" data-raster="true" style="left:72px;top:248px;width:494px;height:344px"></div>`,
    items.map((item, idx) => {
      const y = 238 + idx * 88;
      return [
        `<div class="science-process-card" data-raster="true" style="left:634px;top:${y}px"></div>`,
        textBox("label", itemLabel(item, `Step ${idx + 1}`), 668, y + 18, 418, 22, {
          color: "var(--science-deep)",
          "font-size": "15px",
          "font-weight": "950",
        }),
        textBox("body", itemBody(item), 668, y + 46, 412, 30, {
          color: "var(--science-muted)",
          "font-size": "12px",
          "line-height": "1.32",
        }),
      ].join("\n");
    }).join("\n"),
    scienceFooter(slide, false),
  ].join("\n");
}

function scienceImpactSlide(slide, htmlDir) {
  const image = firstImage(slide);
  const items = normalizeItems(slide.items).slice(0, 3);
  return [
    scienceBg(true),
    image ? imageBox(image, htmlDir, 0, 0, 1280, 326, "science-impact-image", image.fit || "cover") : `<div class="science-impact-band" data-raster="true"></div>`,
    `<div class="science-impact-shade" data-raster="true"></div>`,
    scienceKicker(slide, true),
    textBox("title", slide.claim || slide.title || "Impact", 66, 382, 680, 98, {
      color: "var(--science-cream)",
      "font-size": "38px",
      "line-height": "1.08",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 68, 492, 632, 44, {
      color: "rgba(242,232,212,.72)",
      "font-size": "14px",
      "line-height": "1.36",
    }),
    items.map((item, idx) => {
      const x = 754 + idx * 158;
      return [
        `<div class="science-impact-card" data-raster="true" style="left:${x}px;top:416px"></div>`,
        textBox("label", itemLabel(item, ""), x + 18, 440, 116, 32, {
          color: "var(--science-ember)",
          "font-size": "14px",
          "font-weight": "950",
          "text-align": "center",
        }),
        textBox("body", itemBody(item), x + 18, 488, 118, 54, {
          color: "var(--science-cream)",
          "font-size": "11px",
          "line-height": "1.28",
          "text-align": "center",
        }),
      ].join("\n");
    }).join("\n"),
    scienceFooter(slide, true),
  ].join("\n");
}

function scienceTriptychSlide(slide, htmlDir) {
  const images = normalizeImages(slide).slice(0, 3);
  const items = normalizeItems(slide.items).slice(0, 3);
  return [
    scienceBg(false),
    scienceKicker(slide, false),
    textBox("title", slide.claim || slide.title || "Evidence", 66, 78, 900, 78, {
      color: "var(--science-ink)",
      "font-size": "35px",
      "line-height": "1.08",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 68, 162, 800, 38, {
      color: "var(--science-muted)",
      "font-size": "14px",
      "line-height": "1.36",
    }),
    [0, 1, 2].map((idx) => {
      const x = 72 + idx * 390;
      const item = items[idx] || {};
      const image = images[idx];
      return [
        `<div class="science-trip-card" data-raster="true" style="left:${x}px;top:226px"></div>`,
        image ? imageBox(image, htmlDir, x + 18, 246, 316, 294, "science-trip-image", image.fit || "cover") : `<div class="science-trip-abstract" data-raster="true" style="left:${x + 18}px;top:246px"></div>`,
        textBox("label", itemLabel(item, `Evidence ${idx + 1}`), x + 24, 560, 300, 24, {
          color: "var(--science-deep)",
          "font-size": "17px",
          "font-weight": "950",
        }),
        textBox("body", itemBody(item), x + 24, 590, 292, 44, {
          color: "var(--science-muted)",
          "font-size": "12px",
          "line-height": "1.32",
        }),
      ].join("\n");
    }).join("\n"),
    scienceFooter(slide, false),
  ].join("\n");
}

function scienceClosingSlide(slide, htmlDir) {
  const image = firstImage(slide);
  return [
    scienceBg(true),
    image ? imageBox(image, htmlDir, 0, 0, 1280, 720, "science-closing-image", image.fit || "cover") : scienceAbstractOrb(760, 80, 430, "science-earth-orb"),
    `<div class="science-closing-shade" data-raster="true"></div>`,
    scienceKicker(slide, true),
    textBox("title", slide.claim || slide.title || "Closing", 76, 154, 770, 132, {
      color: "var(--science-cream)",
      "font-size": "44px",
      "line-height": "1.08",
      "font-weight": "950",
    }),
    textBox("body", slide.support || slide.body || "", 80, 328, 690, 82, {
      color: "rgba(242,232,212,.76)",
      "font-size": "17px",
      "line-height": "1.44",
    }),
    `<div class="science-long-rule" data-raster="true" style="left:80px;top:460px;width:248px"></div>`,
    scienceFooter(slide, true),
  ].join("\n");
}

function scienceSlideBody(slide, htmlDir) {
  const layout = String(slide.layout || slide.type || "generic").toLowerCase();
  if (layout.includes("cover")) return scienceCoverSlide(slide, htmlDir);
  if (layout.includes("time-river") || layout.includes("timeline")) return scienceTimeRiverSlide(slide);
  if (layout.includes("scale-day") || layout.includes("scale")) return scienceScaleDaySlide(slide);
  if (layout.includes("mechanism") || layout.includes("system")) return scienceMechanismSlide(slide, htmlDir);
  if (layout.includes("impact") || layout.includes("extinction")) return scienceImpactSlide(slide, htmlDir);
  if (layout.includes("triptych") || layout.includes("evidence")) return scienceTriptychSlide(slide, htmlDir);
  if (layout.includes("close") || layout.includes("awe") || layout.includes("ending")) return scienceClosingSlide(slide, htmlDir);
  return scienceChapterSlide(slide, htmlDir);
}

function coverSlide(slide, htmlDir) {
  const images = normalizeImages(slide);
  const hasImage = images.length > 0;
  const items = normalizeItems(slide.items).slice(0, 3);
  const itemHtml = (items.length ? items : [
    { label: "Input", text: "Source" },
    { label: "Build", text: "System" },
    { label: "Output", text: "Result" },
  ]).map((item, idx) => {
    const x = hasImage ? 74 + idx * 184 : 74 + idx * 318;
    const w = hasImage ? 166 : 286;
    const labelW = hasImage ? 54 : 92;
    const textX = hasImage ? x + 72 : x + 112;
    const textW = hasImage ? 76 : 138;
    return [
      panel(x, 548, w, 76, "metric-panel dark-panel"),
      textBox("label", item.label, x + 18, 567, labelW, 18, { color: "var(--gold)", "font-size": "11px", "font-weight": "800" }),
      textBox("body", item.text || item.value || item.label, textX, 562, textW, 28, { color: "var(--white)", "font-size": "16px", "font-weight": "750" }),
    ].join("\n");
  }).join("\n");
  return [
    `<div class="accent-bar" data-raster="true"></div>`,
    title(slide, 74, 102, hasImage ? 560 : 840, 128, true),
    textBox("body", slide.body || slide.support || "", 76, 274, hasImage ? 536 : 720, 76, {
      color: "var(--pale)",
      "font-size": "16px",
      "line-height": "1.45",
    }),
    `<div class="short-rule" data-raster="true"></div>`,
    hasImage ? imageBox(images[0], htmlDir, 690, 0, 590, 720, "cover-hero-photo", "cover") : "",
    itemHtml,
  ].join("\n");
}

function photoCaptionSlide(slide, htmlDir) {
  const images = normalizeImages(slide);
  const items = normalizeItems(slide.items).slice(0, 3);
  return [
    addKicker(slide),
    title(slide, 72, 84, 720, 72),
    support(slide, 74, 158, 680, 36),
    images.length ? imageBox(images[0], htmlDir, 72, 228, 482, 328, "large-photo", "cover") : panel(72, 228, 482, 328, "empty-visual"),
    items.map((item, idx) => {
      const y = 228 + idx * 110;
      return [
        panel(612, y, 515, 86, "white-panel"),
        textBox("label", item.label || item.value || `Point ${idx + 1}`, 638, y + 18, 430, 20, {
          color: "var(--accent)",
          "font-size": "15px",
          "font-weight": "800",
        }),
        textBox("body", item.text || item.note || "", 638, y + 43, 430, 28, {
          color: "var(--muted)",
          "font-size": "12px",
          "line-height": "1.35",
        }),
      ].join("\n");
    }).join("\n"),
  ].join("\n");
}

function gridSlide(slide, htmlDir) {
  const images = normalizeImages(slide).slice(0, 4);
  const items = normalizeItems(slide.items).slice(0, 4);
  const cells = Math.max(images.length, items.length, 1);
  const cols = cells >= 3 ? 2 : cells;
  const cellW = cols === 2 ? 486 : 720;
  const cellH = cells >= 3 ? 174 : 242;
  const startX = 148;
  const startY = 212;
  return [
    addKicker(slide),
    title(slide, 72, 82, 980, 70),
    support(slide, 74, 154, 880, 34),
    Array.from({ length: cells }).map((_, idx) => {
      const row = Math.floor(idx / cols);
      const col = idx % cols;
      const x = startX + col * (cellW + 46);
      const y = startY + row * (cellH + 32);
      const item = items[idx] || {};
      const image = images[idx];
      return [
        image ? imageBox(image, htmlDir, x, y, cellW, cellH, "grid-image", image.fit || "cover") : panel(x, y, cellW, cellH, "white-panel"),
        item.label ? textBox("label", item.label, x + 18, y + cellH - 40, cellW - 36, 18, {
          color: "var(--gold)",
          "font-size": "14px",
          "font-weight": "800",
        }) : "",
        item.text ? textBox("caption", item.text, x + 18, y + cellH - 20, cellW - 36, 16, {
          color: "var(--white)",
          "font-size": "10px",
        }) : "",
      ].join("\n");
    }).join("\n"),
  ].join("\n");
}

function metricSlide(slide) {
  const items = normalizeItems(slide.items).slice(0, 5);
  const count = Math.max(items.length, 1);
  const gap = 24;
  const w = Math.min(218, (1040 - gap * (count - 1)) / count);
  return [
    addKicker(slide),
    title(slide, 72, 82, 980, 70),
    support(slide, 74, 154, 880, 34),
    items.map((item, idx) => {
      const x = 86 + idx * (w + gap);
      return [
        panel(x, 244, w, 284, "white-panel metric"),
        textBox("metric", item.value || item.label || "", x + 12, 296, w - 24, 58, {
          color: idx % 2 ? "var(--accent2)" : "var(--accent)",
          "font-size": "43px",
          "font-weight": "850",
          "text-align": "center",
        }),
        textBox("label", item.label || item.text || "", x + 18, 370, w - 36, 34, {
          color: "var(--ink)",
          "font-size": "15px",
          "font-weight": "800",
          "text-align": "center",
        }),
        textBox("body", item.text || item.note || "", x + 22, 424, w - 44, 62, {
          color: "var(--muted)",
          "font-size": "12px",
          "line-height": "1.35",
          "text-align": "center",
        }),
      ].join("\n");
    }).join("\n"),
  ].join("\n");
}

function timelineSlide(slide) {
  const items = normalizeItems(slide.items).slice(0, 6);
  return [
    addKicker(slide),
    title(slide, 72, 82, 980, 70),
    support(slide, 74, 154, 880, 34),
    `<div class="timeline-line" data-raster="true"></div>`,
    items.map((item, idx) => {
      const x = 104 + idx * (1000 / Math.max(items.length - 1, 1));
      return [
        `<div class="timeline-dot" data-raster="true" style="left:${x - 7}px"></div>`,
        textBox("label", item.label || item.date || "", x - 58, 294, 116, 22, {
          color: "var(--ink)",
          "font-size": "13px",
          "font-weight": "800",
          "text-align": "center",
        }),
        textBox("body", item.text || item.body || "", x - 76, 388, 152, 60, {
          color: "var(--muted)",
          "font-size": "12px",
          "line-height": "1.35",
          "text-align": "center",
        }),
      ].join("\n");
    }).join("\n"),
  ].join("\n");
}

function compareSlide(slide, htmlDir) {
  const items = normalizeItems(slide.items).slice(0, 2);
  return [
    addKicker(slide),
    title(slide, 72, 82, 980, 70),
    support(slide, 74, 154, 880, 34),
    (items.length ? items : [{ label: "Option A" }, { label: "Option B" }]).map((item, idx) => {
      const x = idx === 0 ? 84 : 674;
      const itemImages = normalizeImages(item);
      return [
        panel(x, 216, 522, 338, "white-panel compare-panel"),
        textBox("label", item.label || "", x + 28, 248, 360, 30, {
          color: idx === 0 ? "var(--accent)" : "var(--accent2)",
          "font-size": "24px",
          "font-weight": "850",
        }),
        textBox("body", item.text || item.body || "", x + 28, 302, 430, 84, {
          color: "var(--ink)",
          "font-size": "15px",
          "line-height": "1.38",
        }),
        itemImages.length ? imageBox(itemImages[0], htmlDir, x + 28, 414, 210, 90, "inline-image", "contain") : "",
      ].join("\n");
    }).join("\n"),
  ].join("\n");
}

function genericSlide(slide) {
  const items = normalizeItems(slide.items).slice(0, 4);
  return [
    addKicker(slide),
    title(slide, 72, 82, 980, 70),
    support(slide, 74, 154, 880, 34),
    textBox("body", slide.body || "", 86, 228, 520, 78, {
      color: "var(--ink)",
      "font-size": "18px",
      "line-height": "1.42",
      "font-weight": "650",
    }),
    items.map((item, idx) => {
      const x = 86 + (idx % 2) * 540;
      const y = 340 + Math.floor(idx / 2) * 112;
      return [
        panel(x, y, 486, 82, "white-panel"),
        textBox("label", item.label || item.value || "", x + 24, y + 18, 400, 20, {
          color: "var(--accent)",
          "font-size": "15px",
          "font-weight": "800",
        }),
        textBox("body", item.text || item.note || "", x + 24, y + 42, 410, 28, {
          color: "var(--muted)",
          "font-size": "12px",
          "line-height": "1.35",
        }),
      ].join("\n");
    }).join("\n"),
  ].join("\n");
}

function slideBody(spec, slide, htmlDir) {
  if (isScienceStorybook(spec)) return scienceSlideBody(slide, htmlDir);
  if (isPremiumEditorial(spec)) return premiumSlideBody(slide, htmlDir);
  const layout = String(slide.layout || slide.type || "generic").toLowerCase();
  if (layout.includes("cover")) return coverSlide(slide, htmlDir);
  if (layout.includes("full-bleed-photo") || layout.includes("photo-caption") || layout.includes("takeaway-photo")) {
    return photoCaptionSlide(slide, htmlDir);
  }
  if (layout.includes("image-grid") || layout.includes("gallery")) return gridSlide(slide, htmlDir);
  if (layout.includes("metric")) return metricSlide(slide);
  if (layout.includes("timeline")) return timelineSlide(slide);
  if (layout.includes("compare") || layout.includes("two-column")) return compareSlide(slide, htmlDir);
  return genericSlide(slide);
}

function renderHtml(spec, slide, htmlDir) {
  const colors = themeFromSpec(spec);
  const font = fontFromSpec(spec);
  const premium = isPremiumEditorial(spec);
  const science = isScienceStorybook(spec);
  const dark = science
    ? scienceIsDark(slide)
    : premium
    ? !String(slide.layout || slide.type || "").toLowerCase().match(/insight|photo|timeline/)
    : String(slide.layout || slide.type || "").toLowerCase().includes("cover");
  const bg = dark ? colors.dark : colors.paper || colors.bg;
  const vars = {
    "--paper": cssHex(colors.paper || colors.bg, DEFAULT_THEME.paper),
    "--bg": cssHex(bg, DEFAULT_THEME.paper),
    "--ink": cssHex(colors.ink, DEFAULT_THEME.ink),
    "--muted": cssHex(colors.muted, DEFAULT_THEME.muted),
    "--accent": cssHex(colors.accent, DEFAULT_THEME.accent),
    "--accent2": cssHex(colors.accent2, DEFAULT_THEME.accent2),
    "--gold": cssHex(colors.gold, DEFAULT_THEME.gold),
    "--hair": cssHex(colors.hair, DEFAULT_THEME.hair),
    "--white": cssHex(colors.white, DEFAULT_THEME.white),
    "--pale": "#dce8e0",
    "--premium-ink": cssHex(colors.ink, "151B20"),
    "--premium-muted": cssHex(colors.muted, "61707D"),
    "--premium-cream": cssHex(colors.cream || colors.white, "F4EEE2"),
    "--premium-paper": cssHex(colors.paper || colors.bg, "ECE4D6"),
    "--premium-deep": cssHex(colors.dark || colors.bg, "101820"),
    "--premium-accent": cssHex(colors.accent, "A65E3A"),
    "--premium-copper": cssHex(colors.copper || colors.gold || colors.accent, "C7873F"),
    "--premium-sky": cssHex(colors.sky || colors.accent2, "6FB7C9"),
    "--science-ink": cssHex(colors.ink, "1C262B"),
    "--science-muted": cssHex(colors.muted, "5D6A6E"),
    "--science-cream": cssHex(colors.cream || colors.white, "F2E8D4"),
    "--science-paper": cssHex(colors.paper || colors.bg, "EFE3CC"),
    "--science-deep": cssHex(colors.dark || colors.bg, "0C1620"),
    "--science-ocean": cssHex(colors.ocean || colors.accent2, "1E7185"),
    "--science-ember": cssHex(colors.ember || colors.accent, "E08635"),
    "--science-moss": cssHex(colors.moss || colors.gold, "8BA16E"),
  };
  const cssVars = Object.entries(vars).map(([key, value]) => `${key}:${value}`).join(";");
  return `<!doctype html>
<html lang="${escapeHtml(font.lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=${PX_W}, initial-scale=1">
<title>${escapeHtml(spec.title || "Presentation")} - ${escapeHtml(slide.number || "")}</title>
<style>
:root{${cssVars};--head:${JSON.stringify(font.head)};--body:${JSON.stringify(font.body)}}
*{box-sizing:border-box}
html,body{margin:0;width:${PX_W}px;height:${PX_H}px;overflow:hidden;background:var(--bg);font-family:var(--body),Arial,sans-serif}
.slide{position:relative;width:${PX_W}px;height:${PX_H}px;overflow:hidden;background:var(--bg);color:var(--ink)}
.box,.panel,.white-panel,.dark-panel,.metric-panel,.empty-visual,img{position:absolute}
.box{white-space:pre-wrap;overflow:hidden;letter-spacing:0}
.title{font-family:var(--head),var(--body),Arial,sans-serif}
.kicker{color:var(--accent2)}
.panel,.white-panel{background:var(--white);border:1px solid var(--hair);border-radius:10px}
.dark-panel{background:#17251f;border-color:#2a4034}
.empty-visual{background:rgba(255,255,255,.68);border:1px solid var(--hair);border-radius:10px}
.hero-image,.large-photo,.grid-image,.inline-image{border-radius:8px}
.cover-hero-photo{border-radius:0}
.accent-bar{position:absolute;left:0;top:0;width:${PX_W}px;height:12px;background:var(--gold)}
.short-rule{position:absolute;left:76px;top:382px;width:144px;height:5px;background:var(--gold)}
.timeline-line{position:absolute;left:104px;top:354px;width:1000px;height:2px;background:var(--hair)}
.timeline-dot{position:absolute;top:346px;width:16px;height:16px;border-radius:999px;background:var(--gold)}
.premium-bg{position:absolute;inset:0}
.premium-bg-dark{background:linear-gradient(135deg,var(--premium-deep) 0%,#16232b 54%,#0c1116 100%)}
.premium-bg-paper{background:linear-gradient(135deg,var(--premium-paper) 0%,#f6f1e8 54%,#d7e1de 100%)}
.premium-left-rule{position:absolute;left:0;top:0;width:13px;height:720px;background:var(--premium-copper)}
.premium-gold-rule{position:absolute;height:5px;background:var(--premium-copper)}
.premium-footer-rule{position:absolute;left:82px;bottom:54px;width:122px;height:1px;background:rgba(199,135,63,.72)}
.premium-cover-image{position:absolute;border-radius:28px 0 0 28px;box-shadow:-30px 0 80px rgba(0,0,0,.35)}
.premium-photo-vignette{position:absolute;left:632px;top:0;width:126px;height:720px;background:linear-gradient(90deg,rgba(16,24,32,.86),rgba(16,24,32,0))}
.premium-abstract-panel{position:absolute;left:660px;top:38px;width:540px;height:628px;border-radius:28px;background:linear-gradient(145deg,#20313d,#0e151b 60%,#c7873f);box-shadow:-30px 0 80px rgba(0,0,0,.36)}
.premium-abstract-small{position:absolute;left:74px;top:268px;width:478px;height:326px;border-radius:22px;background:linear-gradient(145deg,#253b48,#6fb7c9 52%,#c7873f)}
.premium-chip{position:absolute;border-radius:8px}
.dark-chip{background:rgba(244,238,226,.055);border:1px solid rgba(244,238,226,.09)}
.light-chip{background:rgba(255,255,255,.62);border:1px solid rgba(21,27,32,.08)}
.premium-photo{position:absolute;border-radius:22px;box-shadow:0 28px 70px rgba(25,30,34,.18)}
.premium-image-caption-bar{position:absolute;left:74px;top:568px;width:478px;height:26px;background:linear-gradient(90deg,rgba(16,24,32,.7),rgba(16,24,32,0));border-radius:0 0 22px 22px}
.premium-insight-card{position:absolute;width:484px;height:86px;border-radius:16px;background:rgba(255,255,255,.72);border:1px solid rgba(21,27,32,.08);box-shadow:0 16px 45px rgba(25,30,34,.08)}
.premium-metric-card{position:absolute;width:248px;height:310px;border-radius:24px;background:rgba(244,238,226,.07);border:1px solid rgba(244,238,226,.13);box-shadow:0 24px 70px rgba(0,0,0,.22)}
.premium-meter{position:absolute;height:5px;border-radius:99px;background:linear-gradient(90deg,var(--premium-copper),var(--premium-sky))}
.premium-timeline-rail{position:absolute;left:98px;top:360px;width:1086px;height:2px;background:rgba(21,27,32,.18)}
.premium-timeline-node{position:absolute;top:352px;width:16px;height:16px;border-radius:99px;background:var(--premium-copper);box-shadow:0 0 0 8px rgba(166,94,58,.12)}
.premium-timeline-card{position:absolute;width:164px;height:122px;border-radius:18px;background:rgba(255,255,255,.72);border:1px solid rgba(21,27,32,.08);box-shadow:0 16px 45px rgba(25,30,34,.08)}
.premium-side-image{position:absolute;filter:saturate(.92) contrast(1.04)}
.premium-side-abstract{position:absolute;left:0;top:0;width:420px;height:720px;background:linear-gradient(145deg,#6fb7c9,#14242f 48%,#c7873f)}
.premium-side-shade{position:absolute;left:0;top:0;width:520px;height:720px;background:linear-gradient(90deg,rgba(16,24,32,.1),var(--premium-deep))}
.premium-close-dot{position:absolute;width:10px;height:10px;border-radius:99px;background:var(--premium-copper);box-shadow:0 0 0 7px rgba(199,135,63,.14)}
.science-bg{position:absolute;inset:0}
.science-bg-deep{background:radial-gradient(circle at 74% 18%,rgba(30,113,133,.36),transparent 28%),linear-gradient(135deg,var(--science-deep),#101c27 58%,#05090d)}
.science-bg-paper{background:linear-gradient(135deg,var(--science-paper) 0%,#f7f1e3 56%,#d8e0d3 100%)}
.science-starfield{position:absolute;inset:0;background-image:radial-gradient(circle,#f2e8d4 0 1px,transparent 1.5px),radial-gradient(circle,#7fc7d9 0 1px,transparent 1.5px);background-size:92px 92px,137px 137px;background-position:18px 22px,62px 44px;opacity:.28}
.science-haze{position:absolute;inset:0;background:linear-gradient(90deg,rgba(5,9,13,.72),rgba(5,9,13,.18) 54%,rgba(5,9,13,.62))}
.science-paper-grain{position:absolute;inset:0;background-image:linear-gradient(90deg,rgba(28,38,43,.035) 1px,transparent 1px),linear-gradient(rgba(28,38,43,.028) 1px,transparent 1px);background-size:36px 36px;opacity:.45}
.science-left-rail{position:absolute;left:0;top:0;width:12px;height:720px;background:linear-gradient(var(--science-ember),var(--science-ocean))}
.science-long-rule{position:absolute;height:4px;background:linear-gradient(90deg,var(--science-ember),var(--science-ocean));border-radius:99px}
.science-footer-rule{position:absolute;left:68px;bottom:48px;width:126px;height:1px;background:rgba(224,134,53,.64)}
.science-cover-image{position:absolute;border-radius:0 0 0 34px;filter:saturate(.95) contrast(1.05)}
.science-cover-shade{position:absolute;left:500px;top:0;width:400px;height:720px;background:linear-gradient(90deg,var(--science-deep),rgba(12,22,32,0))}
.science-earth-orb{position:absolute;border-radius:999px;background:radial-gradient(circle at 34% 28%,#b9e2e8 0 8%,#2b8ca2 18%,#163a54 38%,#07111a 70%);box-shadow:0 0 90px rgba(61,163,190,.42),inset -60px -34px 90px rgba(0,0,0,.55)}
.science-magma-orb{position:absolute;border-radius:999px;background:radial-gradient(circle at 34% 30%,#f4c66d 0 7%,#e08635 24%,#5b1c15 48%,#10090a 74%);box-shadow:0 0 80px rgba(224,134,53,.34),inset -50px -38px 80px rgba(0,0,0,.55)}
.science-orb-shadow{position:absolute;border-radius:999px;background:radial-gradient(circle,rgba(0,0,0,0),rgba(0,0,0,.42));mix-blend-mode:multiply}
.science-seal{position:absolute;width:104px;height:52px;border-radius:99px;background:rgba(242,232,212,.08);border:1px solid rgba(242,232,212,.16);box-shadow:0 18px 44px rgba(0,0,0,.24)}
.science-river{position:absolute;left:88px;top:356px;width:1090px;height:12px;border-radius:99px;background:linear-gradient(90deg,#27384a,var(--science-ocean),var(--science-moss),var(--science-ember));box-shadow:0 12px 35px rgba(30,113,133,.24)}
.science-river-glow{position:absolute;left:96px;top:314px;width:1076px;height:100px;border-radius:999px;background:radial-gradient(ellipse at center,rgba(30,113,133,.16),transparent 68%)}
.science-river-dot{position:absolute;top:351px;width:18px;height:18px;border-radius:99px;background:var(--science-ember);box-shadow:0 0 0 8px rgba(224,134,53,.15)}
.science-river-card{position:absolute;width:152px;height:112px;border-radius:18px;background:rgba(255,255,255,.68);border:1px solid rgba(28,38,43,.08);box-shadow:0 18px 52px rgba(28,38,43,.08)}
.science-clock{position:absolute;left:86px;top:264px;width:322px;height:322px;border-radius:999px;background:radial-gradient(circle at 50% 50%,rgba(242,232,212,.09),rgba(242,232,212,.03) 52%,rgba(242,232,212,.13) 53%,rgba(242,232,212,.02) 56%);border:2px solid rgba(242,232,212,.2);box-shadow:0 0 80px rgba(30,113,133,.18)}
.science-clock-hand{position:absolute;left:244px;top:308px;width:4px;height:132px;transform-origin:bottom center;transform:rotate(156deg);background:linear-gradient(var(--science-ember),rgba(224,134,53,.1));border-radius:99px}
.science-night-card{position:absolute;width:236px;height:126px;border-radius:20px;background:rgba(242,232,212,.08);border:1px solid rgba(242,232,212,.13);box-shadow:0 20px 60px rgba(0,0,0,.22)}
.science-chapter-image,.science-field-image,.science-impact-image,.science-trip-image,.science-closing-image{position:absolute}
.science-chapter-image{border-radius:30px;box-shadow:0 26px 80px rgba(0,0,0,.36)}
.science-image-frame{position:absolute;border-radius:30px;border:1px solid rgba(242,232,212,.18);box-shadow:inset 0 0 0 1px rgba(255,255,255,.04);pointer-events:none}
.light-frame{border-color:rgba(28,38,43,.1);box-shadow:0 20px 55px rgba(28,38,43,.08)}
.science-mini-card{position:absolute;width:510px;height:62px;border-radius:16px;background:rgba(242,232,212,.07);border:1px solid rgba(242,232,212,.12)}
.science-field-image{border-radius:24px;box-shadow:0 26px 70px rgba(28,38,43,.13)}
.science-diagram-field{position:absolute;left:72px;top:248px;width:494px;height:344px;border-radius:24px;background:radial-gradient(circle at 28% 35%,rgba(30,113,133,.25),transparent 26%),linear-gradient(135deg,#dfe7dc,#f3ecd8)}
.science-process-card{position:absolute;width:470px;height:74px;border-radius:18px;background:rgba(255,255,255,.72);border:1px solid rgba(28,38,43,.08);box-shadow:0 16px 44px rgba(28,38,43,.08)}
.science-impact-band{position:absolute;left:0;top:0;width:1280px;height:326px;background:radial-gradient(circle at 72% 28%,#f2e8d4 0 4%,#e08635 12%,#7b2b1f 24%,#100b0b 58%)}
.science-impact-image{filter:saturate(.96) contrast(1.06)}
.science-impact-shade{position:absolute;left:0;top:0;width:1280px;height:388px;background:linear-gradient(180deg,rgba(6,10,14,.12),rgba(6,10,14,.82))}
.science-impact-card{position:absolute;width:138px;height:158px;border-radius:20px;background:rgba(242,232,212,.08);border:1px solid rgba(242,232,212,.14)}
.science-trip-card{position:absolute;width:352px;height:414px;border-radius:24px;background:rgba(255,255,255,.64);border:1px solid rgba(28,38,43,.08);box-shadow:0 18px 52px rgba(28,38,43,.08)}
.science-trip-image{border-radius:18px}
.science-trip-abstract{position:absolute;width:316px;height:294px;border-radius:18px;background:linear-gradient(145deg,var(--science-ocean),var(--science-moss) 58%,var(--science-ember))}
.science-closing-image{filter:saturate(.92) contrast(1.08)}
.science-closing-shade{position:absolute;inset:0;background:linear-gradient(90deg,rgba(5,9,13,.9),rgba(5,9,13,.54) 48%,rgba(5,9,13,.08)),linear-gradient(0deg,rgba(5,9,13,.75),rgba(5,9,13,.12))}
</style>
</head>
<body>
<section class="slide" data-slide-number="${escapeHtml(slide.number || "")}" data-layout="${escapeHtml(slide.layout || "")}">
${slideBody(spec, slide, htmlDir)}
${premium || science ? "" : textBox("footer", String(slide.number || "").padStart(2, "0"), 1162, 674, 44, 16, {
    color: dark ? "#a9b8ae" : "var(--muted)",
    "font-size": "10px",
    "text-align": "right",
  })}
</section>
</body>
</html>`;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.spec || !args["out-dir"]) {
    console.log(usage());
    process.exit(args.help ? 0 : 2);
  }

  const specPath = resolveWorkspacePath(args.spec, "--spec");
  const outDir = resolveWorkspacePath(args["out-dir"], "--out-dir");
  const manifestPath = resolveWorkspacePath(args.manifest || path.join(outDir, "deck-html-manifest.json"), "--manifest");
  const spec = readJson(specPath);
  if (!Array.isArray(spec.slides) || !spec.slides.length) {
    throw new Error("Spec must include a non-empty slides array.");
  }

  fs.mkdirSync(outDir, { recursive: true });
  const slides = spec.slides.map((slide, idx) => {
    const number = slide.number || idx + 1;
    const fileName = `slide-${String(number).padStart(2, "0")}.html`;
    const filePath = path.join(outDir, fileName);
    fs.writeFileSync(filePath, renderHtml(spec, { ...slide, number }, outDir), "utf8");
    return {
      number,
      layout: slide.layout || slide.type || "generic",
      file: path.relative(process.cwd(), filePath),
    };
  });

  const manifest = {
    ok: true,
    spec: path.relative(process.cwd(), specPath),
    title: spec.title || "Presentation",
    slide_width_px: PX_W,
    slide_height_px: PX_H,
    pptx_width_in: W,
    pptx_height_in: H,
    slide_count: slides.length,
    slides,
  };
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(manifest, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  console.error(usage());
  process.exit(1);
});
