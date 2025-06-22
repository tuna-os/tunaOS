# TunaOS (forks of Bluefin LTS)
This is a set of forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts)
Currently there are 4 forks:
- 🐠 **Yellowfin** `a10s` - based on AlmaLinux Kitten 10
  - This is the closest to upstream Bluefin LTS but with AlmaLinux Kitten 10 which has some diffrences
    - x86_64/v2 support
    - SPICE support for qemu/livirt
    - Secureboot support (though upstream CentOS will have this again soon) 
- 🐟 **Albacore** `:a10` - based on AlmaLinux 10.0
  - **Albacore-server** `:a10-server` - disabled gdm and added "Virtualization host"
- 🎣 **Bluefin-tuna** `F42` - based on Fedora 42
  - This is the tooling and build of Bluefin LTS (based on CentOS 10) ported to Fedora  

I'm currently dailying `bluefin-dx:a10s` and plan on using `bluefin:a10-server` as a replacemnt to my Proxmox server
