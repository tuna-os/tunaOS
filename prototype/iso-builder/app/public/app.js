/* TunaOS ISO Builder GUI — drives the tacklebox WASM engine (tbox.wasm).
 *
 * URL params (shareable presets, tunaOS#667):
 *   ?image=<repo:tag | host/repo:tag>   pre-fill + auto-inspect
 *   ?flatpaks=<comma-separated ids>     override the per-DE default list
 *   ?label=<VOLID>                      volume label
 *   ?initrd=<url>                       tbox-enabled initramfs to embed
 */

const SHIM = "https://relay.tunaos.org";

const FLATPAK_DEFAULTS = {
  gnome: ["org.bootcinstaller.Installer", "org.mozilla.firefox"],
  kde: ["org.tunaos.InstallerKde", "org.mozilla.firefox"],
  // niri/xfce/cosmic default to the GNOME list until they grow their own
  niri: ["org.bootcinstaller.Installer", "org.mozilla.firefox"],
  xfce: ["org.bootcinstaller.Installer", "org.mozilla.firefox"],
  cosmic: ["org.tunaos.InstallerCosmic", "org.mozilla.firefox"],
  none: [],
};

const $ = (id) => document.getElementById(id);

// ── Flatpak checklist + Flathub search ──────────────────────────────────
const fpItems = new Map(); // appId -> { checked, name }

function fpAdd(id, name = "", checked = true) {
  if (!fpItems.has(id)) fpItems.set(id, { checked, name });
  else fpItems.get(id).checked = checked;
  fpRender();
}

function fpCollect() {
  return [...fpItems.entries()].filter(([, v]) => v.checked).map(([k]) => k);
}

function fpRender() {
  const box = $("fplist");
  box.innerHTML = "";
  for (const [id, v] of fpItems) {
    const label = document.createElement("label");
    const cb = Object.assign(document.createElement("input"), { type: "checkbox", checked: v.checked });
    cb.onchange = () => { v.checked = cb.checked; updateShare(); };
    label.appendChild(cb);
    const span = document.createElement("span");
    span.textContent = v.name || id;
    label.appendChild(span);
    if (v.name) {
      const code = document.createElement("code");
      code.textContent = id;
      label.appendChild(code);
    }
    box.appendChild(label);
  }
  updateShare();
}

let fpTimer = null;
async function fpSearch(q) {
  if (!q || q.length < 3) { $("fpresults").innerHTML = ""; return; }
  try {
    const r = await fetch(SHIM + "/flathub/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, filters: [] }),
    });
    const d = await r.json();
    const box = $("fpresults");
    box.innerHTML = "";
    for (const hit of (d.hits || []).slice(0, 6)) {
      if (fpItems.has(hit.app_id) && fpItems.get(hit.app_id).checked) continue;
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = `+ ${hit.name} — ${hit.app_id}`;
      b.onclick = () => { fpAdd(hit.app_id, hit.name); $("fpresults").innerHTML = ""; $("fpsearch").value = ""; };
      box.appendChild(b);
    }
  } catch {
    $("fpresults").innerHTML = "<span style='font-size:.8rem;color:var(--dim)'>Flathub search unavailable</span>";
  }
}
const log = (m) => { $("log").textContent += m + "\n"; $("log").scrollTop = 1e9; };

let facts = null;
let wasmReady = null;

function loadWasm() {
  if (wasmReady) return wasmReady;
  const go = new Go();
  wasmReady = WebAssembly.instantiateStreaming(fetch("tbox.wasm"), go.importObject)
    .then((r) => { go.run(r.instance); log("engine loaded (tacklebox wasm)"); });
  return wasmReady;
}

globalThis.tboxOnProgress = (stage, i, n) => {
  $("stage").textContent = { resolve: "Resolving manifest…", unpack: `Unpacking layer ${i}/${n}`, erofs: "Authoring EROFS live root…", esp: "Authoring EFI system partition…", iso: "Streaming ISO…" }[stage] || stage;
  $("bar").max = n; $("bar").value = i;
};

// "tuna-os/x:y" → ghcr via shim; "quay.io/a/b:c" → that registry direct.
function parseImage(raw) {
  const s = raw.trim();
  const firstSeg = s.split("/")[0];
  if (firstSeg.includes(".") || firstSeg.includes(":")) {
    const host = firstSeg;
    const rest = s.slice(host.length + 1);
    if (host === "ghcr.io") return { registry: SHIM, image: rest };
    return { registry: "https://" + host, image: rest };
  }
  return { registry: SHIM, image: s };
}

async function inspect() {
  const raw = $("image").value;
  if (!raw.includes(":")) { log("image must be <repo>:<tag>"); return; }
  $("introspect").disabled = true;
  $("buildcard").classList.remove("hidden");
  try {
    // Persistent origin storage: multi-GB images live in OPFS during the
    // build; persist() exempts them from eviction (best-effort), and the
    // quota estimate warns before an impossible pull.
    if (navigator.storage?.persist) navigator.storage.persist().catch(() => {});
    if (navigator.storage?.estimate) {
      const { quota, usage } = await navigator.storage.estimate();
      log(`storage quota ≈ ${((quota - usage) / 1e9).toFixed(1)} GB free`);
    }
    await loadWasm();
    const { registry, image } = parseImage(raw);
    log(`inspecting ${image} via ${registry}`);
    facts = JSON.parse(await tboxIntrospect(image, registry));
    const f = $("facts");
    f.classList.remove("hidden");
    f.innerHTML = "";
    const add = (html, cls = "badge") => { const b = document.createElement("span"); b.className = cls; b.innerHTML = html; f.appendChild(b); };
    add(`desktop <b>${facts.desktop}</b>`, "badge de");
    add(`kernel <b>${facts.kernelVer || "none"}</b>`);
    add(`systemd-boot <b>${facts.hasSdBoot ? "in image" : "not shipped"}</b>`);
    add(`<b>${facts.fileCount.toLocaleString()}</b> files`);
    if (fpItems.size === 0) {
      for (const id of FLATPAK_DEFAULTS[facts.desktop] || []) fpAdd(id);
    }
    $("stage").textContent = "Image inspected — ready to build.";
    $("build").disabled = false;
    updateShare();
  } catch (e) {
    log("error: " + e);
    $("stage").textContent = "Inspect failed.";
  } finally {
    $("introspect").disabled = false;
  }
}

async function build() {
  $("build").disabled = true;
  const label = ($("label").value || "TUNAOS").toUpperCase().replace(/[^A-Z0-9_]/g, "_");
  let initrd = null;
  const iurl = $("initrdurl").value.trim();
  try {
    if (iurl) {
      log("fetching tbox initramfs…");
      const r = await fetch(iurl);
      if (!r.ok) throw new Error(`initrd fetch: ${r.status}`);
      initrd = new Uint8Array(await r.arrayBuffer());
      log(`initramfs: ${(initrd.length / 1e6).toFixed(1)} MB`);
    } else {
      $("initrdnote").classList.remove("hidden");
    }
    const name = `tunaos-${($("image").value.split("/").pop() || "image").replace(/[:]/g, "-")}.iso`;
    let sink, chunks = [];
    const autodl = new URLSearchParams(location.search).get("autodl");
    if (window.showSaveFilePicker && !autodl) {
      try {
        const h = await showSaveFilePicker({ suggestedName: name, types: [{ description: "ISO image", accept: { "application/x-iso9660-image": [".iso"] } }] });
        sink = await h.createWritable();
      } catch (e) {
        if (e.name === "AbortError") { log("save dialog dismissed — using download fallback"); }
        else throw e;
      }
    }
    const t0 = performance.now();
    const flatpaks = fpCollect();
    const bytes = await tboxBuildIso({ label, initrd, flatpaks }, (u8) => {
      if (sink) sink.write(u8); else chunks.push(u8.slice());
    });
    if (sink) await sink.close();
    else {
      const blob = new Blob(chunks, { type: "application/x-iso9660-image" });
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: name });
      a.click();
    }
    const dt = ((performance.now() - t0) / 1000).toFixed(1);
    $("stage").textContent = `Done — ${(bytes / 1e9).toFixed(2)} GB in ${dt}s.`;
    log(`iso written: ${bytes} bytes`);
  } catch (e) {
    log("error: " + e);
    $("stage").textContent = "Build failed.";
  } finally {
    $("build").disabled = false;
  }
}

function updateShare() {
  const p = new URLSearchParams();
  if ($("image").value) p.set("image", $("image").value);
  const fl = fpCollect();
  if (fl.length) p.set("flatpaks", fl.join(","));
  if ($("label").value && $("label").value !== "TUNAOS") p.set("label", $("label").value);
  if ($("initrdurl").value) p.set("initrd", $("initrdurl").value);
  const qs = "?" + p.toString();
  $("share").textContent = qs;
  $("sharelink").href = location.origin + location.pathname + qs;
}

$("introspect").onclick = inspect;
$("build").onclick = build;
$("copyshare").onclick = async () => {
  await navigator.clipboard.writeText($("sharelink").href);
  $("copyshare").textContent = "Copied!";
  setTimeout(() => ($("copyshare").textContent = "Copy"), 1500);
};
for (const id of ["image", "label", "initrdurl"]) $(id).addEventListener("input", updateShare);
$("fpsearch").addEventListener("input", (e) => {
  clearTimeout(fpTimer);
  fpTimer = setTimeout(() => fpSearch(e.target.value.trim()), 300);
});

// Apply URL params.
{
  const q = new URLSearchParams(location.search);
  if (q.get("image")) $("image").value = q.get("image");
  if (q.get("flatpaks")) for (const id of q.get("flatpaks").split(",").filter(Boolean)) fpAdd(id);
  if (q.get("label")) $("label").value = q.get("label");
  if (q.get("initrd")) $("initrdurl").value = q.get("initrd");
  updateShare();
  // Deep links prefill only — a page load must never start a multi-GB
  // pull by itself. Opt into auto-run with &autorun=1.
  if (q.get("image") && q.get("autorun") === "1") inspect();
}
