#!/usr/bin/env node
// Prompts for painted TunaOS wallpapers: one per variant × desktop.
//
// Each wallpaper mixes three things:
//   * the variant's emoji, as the centrepiece of a seaside scene;
//   * its base distro, as the dominant colour (build_scripts/lib/variant-identity.tsv);
//   * the desktop's character (GNOME calm, Plasma vivid, COSMIC space-age, ...).
//
//   node scripts/branding/art-prompts.mjs                  # print every prompt (markdown)
//   node scripts/branding/art-prompts.mjs wahoo gnome      # print one
//   GEMINI_API_KEY=... node scripts/branding/art-prompts.mjs --generate wahoo gnome
//
// --generate asks Gemini's image model for the picture and writes it where the
// build picks it up: system_files/usr/share/backgrounds/tunaos/<variant>-<desktop>.jpg
// (build_scripts/desktop/select-wallpaper.sh prefers it over the rendered
// emoji scene). The model is GEMINI_IMAGE_MODEL, default below. Review every
// picture before committing it: look for text, extra limbs, and a centrepiece
// that drifted off-brief.

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repo = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

const identity = Object.fromEntries(
  readFileSync(join(repo, 'build_scripts/lib/variant-identity.tsv'), 'utf8')
    .split('\n')
    .filter((l) => l && !l.startsWith('#'))
    .map((l) => {
      const [id, accent, , base, homage] = l.split('\t');
      return [id, { accent, base, homage }];
    }),
);

// The centrepiece and the place. Every scene is by the sea: TunaOS is a fish.
export const SCENES = {
  yellowfin: { emoji: '🐠', palette: 'warm golden yellows and soft coral pinks', scene: 'a sunlit tropical lagoon seen from a wooden jetty; a large yellowfin tropical fish leaps in a bright arc at the centre, golden light on the water, reef shapes visible through clear shallows' },
  albacore: { emoji: '🐟', palette: 'clear cobalt and cerulean blues', scene: 'an old harbour town at the edge of the open ocean; at the centre a great silver-blue albacore tuna breaks the surface, a school of tuna shimmering beneath it, fishing boats moored along the quay' },
  skipjack: { emoji: '🍣', palette: 'dusky plum and violet twilight, warm lantern light', scene: 'a tiny seaside sushi counter at twilight, lanterns glowing, sliding doors open onto the harbour; at the centre a beautiful plate of nigiri sushi on the counter, the sea and boats beyond' },
  wahoo: { emoji: '🎏', palette: 'deep indigo and soft sky blue', scene: 'a nostalgic Japanese seaside village on a hillside above a bay; at the centre koinobori carp streamers fly from a tall bamboo pole in the sea breeze, tiled roofs, power lines, a harbour and islands on the horizon' },
  bonito: { emoji: '🎣', palette: 'pale morning blues and silver', scene: 'the end of a weathered wooden pier on a calm morning; at the centre a fishing rod bends as a bonito takes the line, a bucket and tackle box beside it, gulls, mist on the far shore' },
  hummingbird: { emoji: '🐦', palette: 'jade and teal greens with hibiscus red', scene: 'a cliffside garden above the sea, hibiscus and trumpet flowers in bloom; at the centre a hummingbird hovers with blurred wings over a flower, the ocean glittering far below' },
  sailfin: { emoji: '⛵', palette: 'fresh leaf greens and a honey-gold sunset', scene: 'a sailboat gliding past green headlands at golden hour; the sail at the centre catches the low sun, a lighthouse on the point, long reflections on the water' },
  guppy: { emoji: '🌈', palette: 'lavender and muted violet after rain', scene: 'a rocky bay just after a summer rain; at the centre a vivid rainbow arcs over the sea, and in a clear tide pool in the foreground tiny colourful guppies swim among pebbles' },
  'bonito-rawhide': { emoji: '🐉', palette: 'slate and steel blues with sea-foam white', scene: 'a wild coast under a dramatic sky; at the centre a serpentine eastern dragon rises from the waves, coiling through spray and cloud, a small shrine gate on the rocks below' },
  gurnard: { emoji: '🤖', palette: 'blueberry blues and the warm glow of streetlights', scene: 'a quiet beach at blue hour; at the centre a small friendly retro robot beachcombs at the waterline, holding up a seashell, a sea robin fish in the shallows beside it, lights of a seaside town behind' },
  grouper: { emoji: '🪸', palette: 'warm terracotta and sunset orange', scene: 'an underwater coral reef lit by warm sunset light filtering down from the surface; at the centre a great branching coral, a big friendly grouper resting beside it, small fish, sea fans, shafts of light' },
  marlin: { emoji: '🚀', palette: 'midnight navy and electric sky blue', scene: 'a sea launch platform at night far out on the ocean; at the centre a rocket lifts off, its flame reflected across the dark water, a blue marlin leaping in the foreground, a sky full of stars' },
  flounder: { emoji: '🐡', palette: 'rose and deep magenta-red', scene: 'a rocky coast at low tide; at the centre a round, puffed-up pufferfish in a clear tide pool, starfish and shells around it, a small fishing village on the headland' },
  'flounder-sid': { emoji: '☢️', palette: 'dark crimson night with a sickly green glow', scene: 'an abandoned seaside research station at night, rusted and overgrown; at the centre a glowing green radiation-symbol sign on the station wall, strange bioluminescent fish glowing in the water below, eerie but beautiful' },
};

// What each desktop feels like, so the wallpaper suits the shell around it.
export const DESKTOPS = {
  gnome: 'calm, airy and uncluttered, soft pastel light and gentle gradients, plenty of open sky near the top, a quiet contemplative mood',
  kde: 'vivid and crisp, rich saturated colour and fine detail, a lively, energetic mood with a little sparkle, the bottom edge kept simple for a taskbar',
  cosmic: 'retro-futurist space-age mood, dusk or night, a sky full of stars and a hint of aurora, bold graphic shapes',
  xfce: 'cosy lo-fi nostalgia, warm late-afternoon light, simple shapes and a gentle film-grain texture, like a memory of a summer holiday',
  niri: 'minimal and panoramic, a wide calm horizon that reads well when scrolled sideways, muted tones with one bright accent',
  pantheon: 'elegant and refined, bright and clean, soft daylight, delicate detail, restful',
};

// Written the way an art director briefs a background painter, not as a tag
// list. Tags like "high detail, 4K, masterpiece" are what push an image model
// towards glossy, over-sharpened AI-looking output; a medium, a light and a
// mood get a painting. Colours are named in words: a hex code in a prompt can
// come back painted as text.
export function prompt(variant, desktop) {
  const s = SCENES[variant];
  const id = identity[variant];
  const d = DESKTOPS[desktop];
  if (!s || !id || !d) throw new Error(`unknown variant/desktop: ${variant} ${desktop}`);
  return [
    `An anime background painting for a desktop wallpaper: ${s.scene}.`,
    `The picture is built around ${s.emoji}, with room to breathe around it; it is the reason the scene exists, not a sticker on top of it.`,
    `Palette: ${s.palette}.`,
    `Feeling: ${d}.`,
    'Painted by hand in gouache and watercolour over soft pencil lines, with paper grain, loose brushwork in the distance and small imperfections, like a background from a hand-drawn Japanese animated film of the 1990s.',
    'Wide 16:9 landscape composition.',
    'Avoid: glossy digital rendering, HDR, over-sharpened edges, airbrushed skin, plastic textures, lens flare, bokeh, excessive detail, text, letters, logos, signatures, watermarks.',
  ].join(' ');
}

async function generate(variant, desktop) {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new Error('set GEMINI_API_KEY to generate');
  const model = process.env.GEMINI_IMAGE_MODEL || 'gemini-3-pro-image-preview';
  const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt(variant, desktop) }] }],
      generationConfig: { responseModalities: ['IMAGE'], imageConfig: { aspectRatio: '16:9' } },
    }),
  });
  if (!res.ok) throw new Error(`${model}: HTTP ${res.status} ${await res.text()}`);
  const body = await res.json();
  const part = body.candidates?.[0]?.content?.parts?.find((p) => p.inlineData);
  if (!part) throw new Error(`${model}: no image in the response`);
  const ext = part.inlineData.mimeType === 'image/png' ? 'png' : 'jpg';
  const out = join(repo, `system_files/usr/share/backgrounds/tunaos/${variant}-${desktop}.${ext}`);
  writeFileSync(out, Buffer.from(part.inlineData.data, 'base64'));
  console.log(`wrote ${out}${ext === 'png' ? '  (PNG: convert to .jpg before committing; the build only looks for .jpg)' : ''}`);
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
const args = process.argv.slice(2);
const gen = args[0] === '--generate';
const [variant, desktop] = gen ? args.slice(1) : args;
if (!isMain) {
  // Imported (tests, other scripts): no CLI.
} else if (gen) {
  await generate(variant, desktop);
} else if (variant) {
  console.log(prompt(variant, desktop || 'gnome'));
} else {
  console.log('# TunaOS wallpaper prompts\n\nGenerated by `node scripts/branding/art-prompts.mjs`.\n');
  for (const v of Object.keys(SCENES)) {
    console.log(`## ${v} ${SCENES[v].emoji}\n`);
    for (const d of Object.keys(DESKTOPS)) console.log(`**${d}**: ${prompt(v, d)}\n`);
  }
}
