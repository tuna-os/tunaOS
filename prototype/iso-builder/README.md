# ISO Builder — moved

The TunaOS ISO Builder (browser/WASM app + CORS relay worker + e2e) now lives
in its own repository:

**https://github.com/tuna-os/iso-builder** · deployed at **https://iso.tunaos.org**

It was extracted from this monorepo so it can build, test, and deploy
independently of the OS image pipeline. The WASM engine it runs is
[tacklebox](https://github.com/tuna-os/tacklebox) compiled to `GOOS=js GOARCH=wasm`.
