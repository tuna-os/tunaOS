# TunaOS (forks of Bluefin LTS)
This is a set of forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts)
Currently there are 4 forks:
- [![Build](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=yellowfin)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml) 🐠 **[Yellowfin](https://github.com/hanthor/tunaOS/tree/yellowfin)** `a10s` - based on [AlmaLinux Kitten 10](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#container-images)
  - This is the closest to upstream Bluefin LTS but with AlmaLinux Kitten 10 which has [some differences](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#how-is-almalinux-os-kitten-different-from-centos-stream) like:
    - x86_64/v2 support
    - SPICE support for qemu/livirt
- [![Build](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=albacore)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml) 🐟 **[Albacore](https://github.com/hanthor/tunaOS/tree/albacore)** - based on AlmaLinux 10.0
  - [![Build](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=albacore-server)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml) **[Albacore-server](https://github.com/hanthor/tunaOS/tree/albacore-server)** `:a10-server` - disabled gdm and added "Virtualization host"
- [![Build](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=bluefon-tuna)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml) 🎣 **[Bluefin-tuna](https://github.com/hanthor/tunaOS/tree/bluefin-tuna)** - based on Fedora 42
  - This is the tooling and build of Bluefin LTS (based on CentOS 10) ported to Fedora  

I'm currently dailying `yellowfin` and plan on using `albacore-server` as a replacemnt to my Proxmox server. Let me know if you are using/liking any of these images. I'm currently assuming I'm the only one using the right now. Open an issue or come hangout at the [AlmaLinux Atomic SIG Chat](https://chat.almalinux.org/almalinux/channels/sigatomic) or the [Universal Blue Discord](https://discord.gg/WEu6BdFEtp)
