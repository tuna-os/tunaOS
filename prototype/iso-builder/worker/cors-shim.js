// Stateless CORS shim for ghcr.io — the only server-side piece of the
// browser ISO builder (ADR 0002). ghcr.io sends no Access-Control-Allow-Origin
// headers, so browser JS cannot read its responses; this Worker relays the
// three read-only endpoints the puller needs and adds the header. It stores
// nothing, publishes nothing, and needs no updates when images change.
//
// Deploy: wrangler deploy (route e.g. ghcr-shim.tunaos.org/*).
//
//   GET /token?scope=repository:tuna-os/<image>:pull
//   GET /v2/tuna-os/<image>/manifests/<ref>
//   GET /v2/tuna-os/<image>/blobs/sha256:<digest>

const UPSTREAM = "https://ghcr.io";
// Only public images in this org — the shim must never become a general relay.
const ORG = "tuna-os";

const PATH_ALLOW = new RegExp(
  `^/(token$|v2/?$|v2/${ORG}/[a-z0-9._-]+/(manifests|blobs)/[A-Za-z0-9._:@-]+$)`
);

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Accept",
  "Access-Control-Expose-Headers":
    "Content-Length, Content-Type, Docker-Content-Digest, WWW-Authenticate",
  "Access-Control-Max-Age": "86400",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    // Flathub search relay: flathub.org's API only answers CORS for its
    // own origins, so the builder's Flathub autocomplete goes through
    // here. POST, tiny JSON bodies, generously cacheable per query.
    if (url.pathname === "/flathub/search") {
      if (request.method !== "POST") {
        return new Response("method not allowed", { status: 405, headers: CORS });
      }
      const body = await request.text();
      if (body.length > 2048) {
        return new Response("query too large", { status: 413, headers: CORS });
      }
      const resp = await fetch("https://flathub.org/api/v2/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      const out = new Response(resp.body, { status: resp.status, headers: CORS });
      out.headers.set("Content-Type", "application/json");
      return out;
    }

    // Cross-distro package search relay: repology maps a package across
    // every distro family (dnf/zypper/pacman/apt/...), so one search box
    // works for any base image. No CORS on repology → proxy it here.
    // ?q=<term>&family=<fedora|opensuse|arch|debian|...>
    if (url.pathname === "/pkgsearch") {
      const q = (url.searchParams.get("q") || "").toLowerCase().replace(/[^a-z0-9._+-]/g, "");
      const family = url.searchParams.get("family") || "";
      if (q.length < 2) {
        return new Response(JSON.stringify([]), { status: 200, headers: { ...CORS, "Content-Type": "application/json" } });
      }
      const UA = { "User-Agent": "tunaos-iso-builder (+https://iso.tunaos.org)", "Accept": "application/json" };
      let projects = {};
      try {
        const rr = await fetch(`https://repology.org/api/v1/projects/?search=${encodeURIComponent(q)}`, { headers: UA });
        if (rr.ok) projects = await rr.json();
      } catch (_) { projects = {}; }
      // The exact-name project is often buried under plugins in search;
      // fetch it directly so the base package always surfaces first.
      try {
        const er = await fetch(`https://repology.org/api/v1/project/${encodeURIComponent(q)}`, { headers: UA });
        if (er.ok) {
          const ee = await er.json();
          if (Array.isArray(ee) && ee.length) projects = { [q]: ee, ...projects };
        }
      } catch (_) {}
      // repology repo prefixes per family (best-effort match).
      const prefixes = {
        fedora: ["fedora"], opensuse: ["opensuse"], arch: ["arch"],
        debian: ["debian", "ubuntu"], gentoo: ["gentoo"], alpine: ["alpine"],
      }[family] || [];
      let out = [];
      for (const [name, entries] of Object.entries(projects || {})) {
        let pick = null;
        for (const e of entries) {
          if (prefixes.some((p) => (e.repo || "").startsWith(p))) { pick = e; break; }
        }
        const any = pick || entries[0];
        if (!any) continue;
        out.push({
          project: name,
          pkg: (pick && (pick.binname || pick.srcname || pick.visiblename)) || name,
          summary: any.summary || "",
          available: !!pick,
          version: any.version || "",
        });
      }
      // Rank: available-in-this-family first, then exact/prefix name match,
      // then shorter names (the base package over its plugins).
      out.sort((a, b) => {
        if (a.available !== b.available) return a.available ? -1 : 1;
        const ax = a.project === q ? 0 : a.project.startsWith(q) ? 1 : 2;
        const bx = b.project === q ? 0 : b.project.startsWith(q) ? 1 : 2;
        if (ax !== bx) return ax - bx;
        return a.project.length - b.project.length;
      });
      out = out.slice(0, 12);
      const o = new Response(JSON.stringify(out), { status: 200, headers: { ...CORS, "Content-Type": "application/json" } });
      o.headers.set("Cache-Control", "public, max-age=600");
      return o;
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405, headers: CORS });
    }
    if (!PATH_ALLOW.test(url.pathname)) {
      return new Response("path not allowed", { status: 403, headers: CORS });
    }

    const upstream = new URL(url.pathname + url.search, UPSTREAM);
    const headers = new Headers();
    for (const h of ["authorization", "accept"]) {
      const v = request.headers.get(h);
      if (v) headers.set(h, v);
    }

    // Blobs are content-addressed and immutable — let Cloudflare's edge cache
    // absorb repeat pulls so ghcr.io isn't hammered.
    const cacheable = url.pathname.includes("/blobs/");
    const resp = await fetch(upstream, {
      method: request.method,
      headers,
      redirect: "follow",
      cf: cacheable ? { cacheEverything: true, cacheTtl: 604800 } : undefined,
    });

    const out = new Headers(resp.headers);
    for (const [k, v] of Object.entries(CORS)) out.set(k, v);
    return new Response(resp.body, { status: resp.status, headers: out });
  },
};
