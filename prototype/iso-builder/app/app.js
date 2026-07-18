/* TunaOS ISO Builder GUI — drives the tacklebox WASM engine (tbox.wasm).
 *
 * URL params (shareable presets, tunaOS#667):
 *   ?image=<repo:tag | host/repo:tag>   pre-fill + auto-inspect
 *   ?flatpaks=<comma-separated ids>     override the per-DE default list
 *   ?label=<VOLID>                      volume label
 *   ?initrd=<url>                       tbox-enabled initramfs to embed
 */

const SHIM = "https://ghcr-shim.trogdor30001.workers.dev";

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
    if (!$("flatpaks").value.trim()) {
      $("flatpaks").value = (FLATPAK_DEFAULTS[facts.desktop] || []).join("\n");
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
    const flatpaks = $("flatpaks").value.trim().split(/\s+/).filter(Boolean);
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
  const fl = $("flatpaks").value.trim().split(/\s+/).filter(Boolean);
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
for (const id of ["image", "flatpaks", "label", "initrdurl"]) $(id).addEventListener("input", updateShare);

// Apply URL params.
{
  const q = new URLSearchParams(location.search);
  if (q.get("image")) $("image").value = q.get("image");
  if (q.get("flatpaks")) $("flatpaks").value = q.get("flatpaks").split(",").join("\n");
  if (q.get("label")) $("label").value = q.get("label");
  if (q.get("initrd")) $("initrdurl").value = q.get("initrd");
  updateShare();
  // Deep links prefill only — a page load must never start a multi-GB
  // pull by itself. Opt into auto-run with &autorun=1.
  if (q.get("image") && q.get("autorun") === "1") inspect();
}
