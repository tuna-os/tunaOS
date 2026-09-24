// Builds one variant's wallpaper as an SVG scene.
//
// Every wallpaper shares the same TunaOS world: open water, light from the
// surface, the deep below. The variant's base distro gives the water its
// colour (Arch blue for marlin, Ubuntu orange for grouper), and the variant's
// Noto Emoji sets the scene: marlin's 🚀 breaks the surface into a night sky,
// sailfin's ⛵ sits on a sunset horizon, grouper's 🪸 is a whole reef.
//
// Emoji come from scripts/branding/emoji/<codepoint>.svg (Noto Emoji, Apache
// License 2.0). Placement is seeded by the variant id, so a re-render is
// byte-stable unless an input changes.

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const EMOJI_DIR = join(dirname(fileURLToPath(import.meta.url)), 'emoji');
const EMOJI = {
  fish: '1f41f', tropical: '1f420', puffer: '1f421', sushi: '1f363',
  carp: '1f38f', rod: '1f3a3', bird: '1f426', boat: '26f5', rainbow: '1f308',
  dragon: '1f409', robot: '1f916', coral: '1fab8', rocket: '1f680',
  radioactive: '2622', shell: '1f41a', moon: '1f319', star: '2b50',
  sparkle: '2728', hibiscus: '1f33a', bubbles: '1fae7', jelly: '1fabc',
  crab: '1f980', octopus: '1f419', cloud: '2601', sun: '2600',
  barrel: '1f6e2', herb: '1f33f', whale: '1f40b',
};

const W = 3840;
const H = 2160;

// ── colour ──────────────────────────────────────────────────────────────────
function rgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function mix(a, b, t) {
  const x = rgb(a), y = rgb(b);
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('');
}

// ── deterministic randomness ────────────────────────────────────────────────
function seeded(seed) {
  let s = 2166136261;
  for (const ch of seed) s = Math.imul(s ^ ch.charCodeAt(0), 16777619) >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32);
}

// ── emoji as <symbol>s ──────────────────────────────────────────────────────
// Noto's SVGs all reuse ids like SVGID_1_, so two different emoji in one
// document would steal each other's gradients. Prefix every id per emoji.
function symbolFor(name, code) {
  const raw = readFileSync(join(EMOJI_DIR, `${code}.svg`), 'utf8');
  const viewBox = (raw.match(/viewBox="([^"]+)"/) || [, '0 0 128 128'])[1];
  let body = raw
    .replace(/<\?xml[^>]*>/, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/^[\s\S]*?<svg\b[^>]*>/, '')
    .replace(/<\/svg>\s*$/, '');
  const p = `e-${name}-`;
  body = body
    .replace(/\bid="([^"]+)"/g, `id="${p}$1"`)
    .replace(/url\(#([^)]+)\)/g, `url(#${p}$1)`)
    .replace(/(xlink:href|href)="#([^"]+)"/g, `$1="#${p}$2"`);
  return `<symbol id="e-${name}" viewBox="${viewBox}">${body}</symbol>`;
}

// ── scene builder ───────────────────────────────────────────────────────────
class Scene {
  constructor(id, accent) {
    this.id = id;
    this.accent = accent;
    this.r = seeded(id);
    this.defs = [];
    this.layers = [];
    this.used = new Set();
  }
  rand(a, b) { return a + (b - a) * this.r(); }
  add(svg) { this.layers.push(svg); return this; }
  def(svg) { this.defs.push(svg); return this; }

  // Place an emoji centred on (x, y) at `size` px. `flip` mirrors it, so a
  // left-facing Noto fish swims right. `depth` 0..1 pushes it back: smaller
  // contrast, a little blur, tinted towards the water.
  emoji(name, x, y, size, { rot = 0, flip = false, opacity = 1, depth = 0, filter = '' } = {}) {
    this.used.add(name);
    const f = filter || (depth > 0.66 ? 'url(#far)' : depth > 0.33 ? 'url(#mid)' : '');
    const o = opacity * (1 - depth * 0.55);
    const t = `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${rot}) scale(${flip ? -1 : 1} 1)`;
    return this.add(
      `<use href="#e-${name}" x="${-size / 2}" y="${-size / 2}" width="${size}" height="${size}" transform="${t}" opacity="${o.toFixed(2)}"${f ? ` filter="${f}"` : ''}/>`,
    );
  }

  // ── environments ──
  underwater({ top, bottom = '#04060c', rays = 7, glowAt = [0.5, 0.45], glow = 0.3 } = {}) {
    const surface = top || mix(this.accent, '#0b1a2b', 0.4);
    const mid = mix(this.accent, bottom, 0.75);
    this.def(`<linearGradient id="sea" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${surface}"/><stop offset="0.5" stop-color="${mid}"/><stop offset="1" stop-color="${bottom}"/></linearGradient>`);
    this.add(`<rect width="${W}" height="${H}" fill="url(#sea)"/>`);
    this.lightRays(0, H, rays);
    this.def(`<radialGradient id="glow" cx="${glowAt[0]}" cy="${glowAt[1]}" r="0.35">
      <stop offset="0" stop-color="${this.accent}" stop-opacity="${glow}"/><stop offset="1" stop-color="${this.accent}" stop-opacity="0"/></radialGradient>`);
    this.add(`<rect width="${W}" height="${H}" fill="url(#glow)"/>`);
    return this;
  }

  lightRays(y0, y1, n) {
    const shafts = [];
    for (let i = 0; i < n; i++) {
      const x = W * this.rand(0.1, 0.9), w = W * this.rand(0.015, 0.05);
      const lean = W * this.rand(0.06, 0.16) * (this.r() < 0.5 ? -1 : 1);
      const len = (y1 - y0) * 0.95;
      shafts.push(`<polygon points="${x - w},${y0 - 200} ${x + w},${y0 - 200} ${x + w * 3 + lean},${y0 + len} ${x - w * 3 + lean},${y0 + len}" fill="url(#ray)" opacity="${this.rand(0.04, 0.09).toFixed(3)}"/>`);
    }
    return this.add(`<g filter="url(#soft)" clip-path="url(#below${y0})">${shafts.join('')}</g>`)
      .def(`<clipPath id="below${y0}"><rect x="0" y="${y0}" width="${W}" height="${y1 - y0}"/></clipPath>`);
  }

  // Sky above `horizon`, sea below it, with a bright rippled waterline.
  surface(horizon, { skyTop, skyBottom, sea } = {}) {
    const seaTop = sea || mix(this.accent, '#0b1a2b', 0.35);
    this.def(`<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${skyTop}"/><stop offset="1" stop-color="${skyBottom}"/></linearGradient>`);
    this.def(`<linearGradient id="deep" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${seaTop}"/><stop offset="0.55" stop-color="${mix(this.accent, '#04060c', 0.8)}"/><stop offset="1" stop-color="#04060c"/></linearGradient>`);
    this.add(`<rect width="${W}" height="${horizon}" fill="url(#sky)"/>`);
    this.add(`<rect y="${horizon}" width="${W}" height="${H - horizon}" fill="url(#deep)"/>`);
    this.lightRays(horizon, H, 6);
    // Ripples on the waterline, brightest at the surface.
    for (let i = 0; i < 5; i++) {
      const y = horizon + i * 14;
      this.add(`<path d="${wavePath(y, 6 + i * 2, W / this.rand(4, 9), this.rand(0, 6), 8)}" fill="none" stroke="#ffffff" stroke-opacity="${(0.28 - i * 0.05).toFixed(2)}" stroke-width="${4 - i * 0.6}"/>`);
    }
    return this;
  }

  seafloor(y, colour) {
    const sand = colour || mix('#c9a877', this.accent, 0.25);
    this.def(`<linearGradient id="sand" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${mix(sand, '#04060c', 0.45)}"/><stop offset="1" stop-color="${mix(sand, '#04060c', 0.85)}"/></linearGradient>`);
    this.add(`<path d="${wavePath(y, 30, W / 1.6, this.rand(0, 6)) + ` L${W} ${H} L0 ${H} Z`}" fill="url(#sand)"/>`);
    this.add(`<path d="${wavePath(y + 70, 22, W / 2.3, this.rand(0, 6)) + ` L${W} ${H} L0 ${H} Z`}" fill="#000" opacity="0.25"/>`);
    return this;
  }

  bubbles(n, { x = [0, 1], y = [0.2, 1], colour = '#ffffff' } = {}) {
    for (let i = 0; i < n; i++) {
      const cx = W * this.rand(...x), cy = H * this.rand(...y), rad = 4 + 18 * this.r() ** 2;
      this.add(`<circle cx="${cx.toFixed(0)}" cy="${cy.toFixed(0)}" r="${rad.toFixed(1)}" fill="${colour}" fill-opacity="0.04" stroke="${colour}" stroke-opacity="${this.rand(0.12, 0.3).toFixed(2)}" stroke-width="2.5"/>`);
    }
    return this;
  }

  stars(n, yMax) {
    for (let i = 0; i < n; i++) {
      this.add(`<circle cx="${(W * this.r()).toFixed(0)}" cy="${(yMax * this.r() ** 1.3).toFixed(0)}" r="${(1.5 + 3.5 * this.r() ** 3).toFixed(1)}" fill="#fff" opacity="${this.rand(0.35, 0.95).toFixed(2)}"/>`);
    }
    return this;
  }

  glowDisc(x, y, radius, colour, opacity) {
    const gid = `g${this.defs.length}`;
    this.def(`<radialGradient id="${gid}"><stop offset="0" stop-color="${colour}" stop-opacity="${opacity}"/><stop offset="1" stop-color="${colour}" stop-opacity="0"/></radialGradient>`);
    return this.add(`<circle cx="${x}" cy="${y}" r="${radius}" fill="url(#${gid})"/>`);
  }

  // A school of `name` along a gentle curve, facing `dir` (1 = right).
  school(name, n, { from, to, sway = 0.08, size = [80, 220], dir = 1, depthBias = 0.5 }) {
    const fish = [];
    for (let i = 0; i < n; i++) {
      const t = this.r();
      const x = W * (from[0] + (to[0] - from[0]) * t) + this.rand(-1, 1) * W * 0.05;
      const y = H * (from[1] + (to[1] - from[1]) * t + Math.sin(t * Math.PI * 2) * sway) + this.rand(-1, 1) * H * 0.06;
      const depth = Math.min(1, this.r() * depthBias * 1.6);
      fish.push({ x, y, s: size[1] - (size[1] - size[0]) * depth, depth });
    }
    fish.sort((a, b) => b.depth - a.depth); // far ones first
    const slope = Math.atan2((to[1] - from[1]) * H, (to[0] - from[0]) * W) * 180 / Math.PI;
    for (const f of fish) this.emoji(name, f.x, f.y, f.s, { flip: dir > 0, rot: dir > 0 ? slope * 0.6 : -slope * 0.6, depth: f.depth });
    return this;
  }

  render() {
    const symbols = [...this.used].map((n) => symbolFor(n, EMOJI[n])).join('\n');
    return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs>
  <linearGradient id="ray" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <filter id="soft" filterUnits="userSpaceOnUse" x="${-W * 0.2}" y="${-H * 0.4}" width="${W * 1.4}" height="${H * 1.6}"><feGaussianBlur stdDeviation="${W / 110}"/></filter>
  <filter id="mid" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.5"/></filter>
  <filter id="far" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="6"/></filter>
  <filter id="lift" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="22" stdDeviation="30" flood-color="#000" flood-opacity="0.45"/></filter>
  <filter id="mutant" x="-30%" y="-30%" width="160%" height="160%"><feColorMatrix type="hueRotate" values="75"/><feDropShadow dx="0" dy="0" stdDeviation="26" flood-color="#9dff3a" flood-opacity="0.7"/></filter>
  ${this.defs.join('\n  ')}
  ${symbols}
</defs>
${this.layers.join('\n')}
</svg>`;
  }
}

function wavePath(y, amp, len, phase, step = 40) {
  let d = `M0 ${y}`;
  for (let x = step; x <= W + step; x += step) d += ` L${x} ${(y + amp * Math.sin((x / len) * 2 * Math.PI + phase)).toFixed(1)}`;
  return d;
}

// ── the scenes ──────────────────────────────────────────────────────────────
const SCENES = {
  // A school of tuna streaming up through the light.
  albacore(s) {
    s.underwater({ glowAt: [0.55, 0.4] }).bubbles(26);
    s.school('fish', 34, { from: [0.05, 0.85], to: [0.95, 0.2], size: [70, 230] });
    s.emoji('fish', W * 0.58, H * 0.44, 460, { flip: true, rot: -14, filter: 'url(#lift)' });
  },

  // Tropical fish circling a patch of reef.
  yellowfin(s) {
    s.underwater({ glowAt: [0.5, 0.45], glow: 0.35 }).bubbles(20).seafloor(H * 0.86);
    for (const [x, sz] of [[0.08, 420], [0.18, 300], [0.86, 460], [0.95, 280]]) s.emoji('coral', W * x, H * 0.84 - sz * 0.35, sz);
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2, rx = W * 0.23, ry = H * 0.2;
      const depth = (Math.sin(a) + 1) / 2 * 0.8;
      s.emoji('tropical', W * 0.5 + Math.cos(a) * rx, H * 0.45 + Math.sin(a) * ry * 0.7, 190 - depth * 90, { flip: Math.sin(a) < 0, depth });
    }
    s.emoji('tropical', W * 0.5, H * 0.45, 520, { filter: 'url(#lift)' });
  },

  // A school of sushi, migrating in formation. One real fish tags along.
  skipjack(s) {
    s.underwater({ glowAt: [0.45, 0.4] }).bubbles(24);
    // A chevron, like migrating fish, pointing right.
    const lead = [0.7, 0.44];
    for (let i = 0; i < 13; i++) {
      const row = Math.ceil(i / 2), side = i % 2 ? 1 : -1;
      const x = lead[0] - row * 0.075, y = lead[1] + side * row * 0.055;
      s.emoji('sushi', W * x, H * y, i === 0 ? 420 : 300 - row * 26, { rot: -6, depth: row * 0.07, filter: i === 0 ? 'url(#lift)' : '' });
    }
    s.emoji('fish', W * 0.14, H * 0.78, 220, { flip: true, rot: -10, depth: 0.3 });
  },

  // Koinobori flying over the sea on a bright day.
  wahoo(s) {
    const hz = H * 0.64;
    s.surface(hz, { skyTop: mix(s.accent, '#0a1020', 0.35), skyBottom: mix(s.accent, '#bcd6ff', 0.55) });
    for (const [x, y, sz] of [[0.18, 0.16, 360], [0.72, 0.1, 300], [0.9, 0.28, 240], [0.4, 0.3, 200]]) s.emoji('cloud', W * x, H * y, sz, { opacity: 0.9, depth: 0.3 });
    s.emoji('carp', W * 0.56, H * 0.34, 900, { rot: 4, filter: 'url(#lift)' });
    s.school('fish', 10, { from: [0.1, 0.9], to: [0.9, 0.78], size: [70, 150], depthBias: 1 });
  },

  // A line dropped from above, and a fish about to take it.
  bonito(s) {
    const hz = H * 0.42;
    s.surface(hz, { skyTop: mix(s.accent, '#0a1424', 0.45), skyBottom: mix(s.accent, '#d9ecff', 0.55) });
    s.emoji('cloud', W * 0.78, H * 0.12, 320, { opacity: 0.85, depth: 0.3 });
    s.emoji('rod', W * 0.2, H * 0.2, 560, { filter: 'url(#lift)' });
    const tip = [W * 0.2 + 250, H * 0.2 - 250], hook = [W * 0.6, H * 0.72];
    s.add(`<path d="M${tip[0]} ${tip[1]} Q ${W * 0.5} ${H * 0.05} ${hook[0]} ${hook[1]}" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="4"/>`);
    s.add(`<path d="M${hook[0]} ${hook[1]} v40 a26 26 0 1 1 -40 12" fill="none" stroke="#dfe7ee" stroke-width="7" stroke-linecap="round"/>`);
    s.emoji('fish', W * 0.72, H * 0.76, 360, { rot: 8, filter: 'url(#lift)' });
    s.school('fish', 8, { from: [0.05, 0.9], to: [0.45, 0.62], size: [80, 150], depthBias: 1 });
    s.bubbles(14, { y: [0.5, 1] });
  },

  // A hummingbird over the water, flowers drifting on the surface.
  hummingbird(s) {
    const hz = H * 0.7;
    s.surface(hz, { skyTop: mix(s.accent, '#07131a', 0.55), skyBottom: mix(s.accent, '#e8fff8', 0.5) });
    s.glowDisc(W * 0.82, H * 0.2, 520, '#fff6c8', 0.55);
    s.emoji('sun', W * 0.82, H * 0.2, 300, { opacity: 0.95 });
    s.emoji('cloud', W * 0.2, H * 0.14, 300, { opacity: 0.85, depth: 0.3 });
    s.emoji('bird', W * 0.45, H * 0.38, 600, { rot: -8, filter: 'url(#lift)' });
    for (const [x, sz] of [[0.12, 170], [0.3, 130], [0.6, 190], [0.78, 140], [0.93, 120]]) s.emoji('hibiscus', W * x, hz - sz * 0.15, sz, { rot: s.rand(-20, 20) });
    s.school('tropical', 7, { from: [0.1, 0.92], to: [0.9, 0.84], size: [70, 130], depthBias: 1 });
  },

  // A sail on the horizon at sundown.
  sailfin(s) {
    const hz = H * 0.6;
    s.surface(hz, { skyTop: mix(s.accent, '#081208', 0.7), skyBottom: '#ffb070', sea: mix(s.accent, '#1a2a2a', 0.45) });
    s.glowDisc(W * 0.6, hz, 900, '#ffd08a', 0.55);
    s.add(`<clipPath id="sky-only"><rect width="${W}" height="${hz}"/></clipPath>`);
    s.add(`<circle cx="${W * 0.6}" cy="${hz + 40}" r="260" fill="#ffe2a8" clip-path="url(#sky-only)"/>`);
    s.stars(40, H * 0.25);
    // Sun glitter on the water.
    for (let i = 0; i < 14; i++) s.add(`<rect x="${W * 0.6 - s.rand(40, 260)}" y="${hz + 20 + i * 38}" width="${s.rand(120, 520)}" height="6" rx="3" fill="#ffe2a8" opacity="${(0.5 - i * 0.03).toFixed(2)}"/>`);
    s.emoji('boat', W * 0.42, hz - 250, 560, { filter: 'url(#lift)' });
    s.emoji('boat', W * 0.42, hz + 260, 560, { opacity: 0.18, filter: 'url(#mid)' }); // reflection, flipped below
    s.layers[s.layers.length - 1] = s.layers[s.layers.length - 1].replace('scale(-1 1)', 'scale(1 -1)').replace('scale(1 1)', 'scale(1 -1)');
    s.school('fish', 6, { from: [0.08, 0.92], to: [0.35, 0.82], size: [70, 120], depthBias: 1 });
  },

  // A rainbow over the sea, and the guppies it scattered below.
  guppy(s) {
    const hz = H * 0.56;
    s.surface(hz, { skyTop: mix(s.accent, '#0a0814', 0.55), skyBottom: mix(s.accent, '#f4dcff', 0.55) });
    // Noto's rainbow is a quarter arc rising from the left: stand its foot on
    // the horizon and let a cloud hide where it lands.
    s.glowDisc(W * 0.42, hz - 300, 900, '#fff4e0', 0.25);
    s.emoji('rainbow', W * 0.44, hz - 470, 1300, { opacity: 0.9 });
    s.emoji('cloud', W * 0.25, hz - 110, 420, { opacity: 0.97 });
    s.emoji('cloud', W * 0.64, hz - 110, 380, { opacity: 0.97, flip: true });
    s.emoji('cloud', W * 0.86, H * 0.14, 260, { opacity: 0.8, depth: 0.3 });
    for (let i = 0; i < 34; i++) {
      const depth = s.r();
      s.emoji('tropical', W * s.rand(0.03, 0.97), H * s.rand(0.64, 0.97), 170 - depth * 100, { flip: s.r() < 0.5, depth, rot: s.rand(-12, 12) });
    }
  },

  // A dragon rising out of the deep, trailing sparks.
  'bonito-rawhide'(s) {
    s.underwater({ glowAt: [0.5, 0.48], glow: 0.45, bottom: '#020308' }).bubbles(40, { colour: mix(s.accent, '#ffffff', 0.6) });
    for (let i = 0; i < 9; i++) s.emoji('sparkle', W * s.rand(0.2, 0.8), H * s.rand(0.15, 0.85), s.rand(60, 140), { opacity: 0.8, depth: s.rand(0, 0.6) });
    s.emoji('dragon', W * 0.5, H * 0.48, 980, { filter: 'url(#lift)' });
    s.school('fish', 8, { from: [0.02, 0.2], to: [0.2, 0.9], size: [70, 130], dir: -1, depthBias: 1 });
    s.school('fish', 8, { from: [0.8, 0.9], to: [0.98, 0.2], size: [70, 130], depthBias: 1 });
  },

  // The sea robin: a robot on the seabed, keeping a crab company.
  gurnard(s) {
    s.underwater({ glowAt: [0.5, 0.55], glow: 0.35 }).bubbles(22).seafloor(H * 0.8);
    s.glowDisc(W * 0.5, H * 0.72, 700, '#dff3ff', 0.18);
    for (const [x, sz] of [[0.06, 380], [0.15, 280], [0.84, 320], [0.94, 420]]) s.emoji('herb', W * x, H * 0.79 - sz * 0.38, sz, { rot: s.rand(-8, 8) });
    s.emoji('robot', W * 0.5, H * 0.62, 560, { filter: 'url(#lift)' });
    s.emoji('crab', W * 0.66, H * 0.8, 230, { filter: 'url(#lift)' });
    s.emoji('shell', W * 0.36, H * 0.84, 150);
    s.emoji('shell', W * 0.77, H * 0.9, 120, { rot: 30 });
    s.school('fish', 12, { from: [0.08, 0.35], to: [0.92, 0.18], size: [70, 150], depthBias: 1 });
  },

  // A whole reef.
  grouper(s) {
    s.underwater({ glowAt: [0.5, 0.35], glow: 0.35 }).bubbles(20).seafloor(H * 0.82);
    s.emoji('jelly', W * 0.16, H * 0.24, 280, { opacity: 0.85, depth: 0.35 });
    s.emoji('jelly', W * 0.26, H * 0.12, 160, { opacity: 0.8, depth: 0.7 });
    // Back row first (dimmer), then the front row of big coral heads.
    for (const [x, sz] of [[0.09, 300], [0.3, 260], [0.44, 280], [0.58, 300], [0.71, 260], [0.9, 300]]) s.emoji('coral', W * x, H * 0.76 - sz * 0.3, sz, { flip: s.r() < 0.5, depth: 0.45 });
    for (const [x, sz] of [[0.2, 240], [0.66, 220], [0.99, 260]]) s.emoji('herb', W * x, H * 0.8 - sz * 0.35, sz);
    for (const [x, sz] of [[0.03, 460], [0.15, 560], [0.36, 480], [0.5, 700], [0.77, 540], [0.93, 480]]) s.emoji('coral', W * x, H * 0.84 - sz * 0.3, sz, { flip: s.r() < 0.5 });
    s.emoji('octopus', W * 0.8, H * 0.5, 360, { rot: -8, filter: 'url(#lift)' });
    s.school('tropical', 10, { from: [0.12, 0.55], to: [0.62, 0.35], size: [90, 200], depthBias: 0.8 });
    s.emoji('fish', W * 0.4, H * 0.3, 260, { flip: true, filter: 'url(#lift)' });
  },

  // Liftoff: straight out of the sea into the night.
  marlin(s) {
    const hz = H * 0.66;
    s.surface(hz, { skyTop: '#02040c', skyBottom: mix(s.accent, '#050a18', 0.55) });
    s.stars(260, hz * 0.95);
    for (const [x, y, sz] of [[0.14, 0.22, 90], [0.78, 0.12, 70], [0.9, 0.42, 60], [0.3, 0.08, 55]]) s.emoji('star', W * x, H * y, sz, { opacity: 0.9 });
    s.emoji('moon', W * 0.84, H * 0.2, 300);
    // Exhaust trail from the splash to the rocket.
    s.def(`<linearGradient id="trail" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0.05"/><stop offset="0.7" stop-color="#ffd27a" stop-opacity="0.55"/><stop offset="1" stop-color="#ff8a3a" stop-opacity="0.9"/></linearGradient>`);
    s.add(`<path d="M${W * 0.5 - 140} ${hz} C ${W * 0.5 - 60} ${H * 0.5}, ${W * 0.5 - 30} ${H * 0.4}, ${W * 0.5 - 12} ${H * 0.36} L ${W * 0.5 + 12} ${H * 0.36} C ${W * 0.5 + 30} ${H * 0.4}, ${W * 0.5 + 60} ${H * 0.5}, ${W * 0.5 + 140} ${hz} Z" fill="url(#trail)" filter="url(#mid)"/>`);
    // Splash.
    for (let i = 0; i < 28; i++) {
      const a = s.rand(-Math.PI * 0.95, -Math.PI * 0.05), d = s.rand(60, 320);
      s.add(`<circle cx="${(W * 0.5 + Math.cos(a) * d).toFixed(0)}" cy="${(hz + Math.sin(a) * d * 0.6).toFixed(0)}" r="${s.rand(4, 16).toFixed(1)}" fill="#e8f6ff" opacity="${s.rand(0.4, 0.9).toFixed(2)}"/>`);
    }
    s.add(`<ellipse cx="${W * 0.5}" cy="${hz}" rx="360" ry="34" fill="#e8f6ff" opacity="0.5" filter="url(#mid)"/>`);
    s.emoji('rocket', W * 0.5, H * 0.26, 620, { rot: -45, filter: 'url(#lift)' });
    s.school('fish', 9, { from: [0.1, 0.95], to: [0.9, 0.82], size: [70, 150], depthBias: 1 });
  },

  // A pufferfish at home on the sand.
  flounder(s) {
    s.underwater({ glowAt: [0.5, 0.5], glow: 0.35 }).bubbles(34).seafloor(H * 0.84);
    for (const [x, sz] of [[0.07, 360], [0.93, 400]]) s.emoji('coral', W * x, H * 0.83 - sz * 0.33, sz);
    s.emoji('herb', W * 0.17, H * 0.8, 260);
    s.emoji('shell', W * 0.3, H * 0.88, 150, { rot: -20 });
    s.emoji('shell', W * 0.7, H * 0.9, 170, { rot: 15 });
    s.emoji('puffer', W * 0.5, H * 0.5, 600, { filter: 'url(#lift)' });
    s.emoji('bubbles', W * 0.43, H * 0.3, 160, { opacity: 0.9 });
    s.school('fish', 9, { from: [0.62, 0.3], to: [0.98, 0.16], size: [70, 140], depthBias: 1 });
  },

  // Something leaked into the deep, and the locals have adapted.
  'flounder-sid'(s) {
    s.underwater({ bottom: '#010203', glowAt: [0.5, 0.7], glow: 0.25, rays: 4 }).seafloor(H * 0.84, '#3a3f2a');
    s.glowDisc(W * 0.5, H * 0.72, 900, '#9dff3a', 0.32);
    s.bubbles(40, { colour: '#c8ff8a', y: [0.3, 0.85], x: [0.3, 0.7] });
    s.emoji('barrel', W * 0.5, H * 0.72, 420, { filter: 'url(#lift)' });
    s.emoji('radioactive', W * 0.5, H * 0.4, 300, { opacity: 0.95 });
    s.emoji('puffer', W * 0.25, H * 0.45, 380, { flip: true, filter: 'url(#mutant)' });
    s.emoji('puffer', W * 0.78, H * 0.3, 260, { filter: 'url(#mutant)' });
    s.emoji('fish', W * 0.86, H * 0.62, 200, { filter: 'url(#mutant)', depth: 0.3 });
  },
};
// The generic TunaOS wallpaper: albacore's school in plain ocean blue.
SCENES.tunaos = SCENES.albacore;

export function wallpaperSvg({ id, accent }) {
  const build = SCENES[id];
  if (!build) throw new Error(`no wallpaper scene for variant '${id}'`);
  const s = new Scene(id, accent);
  build(s);
  return s.render();
}

export const SCENE_IDS = Object.keys(SCENES);
