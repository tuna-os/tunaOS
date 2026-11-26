#!/usr/bin/bash
# Print mksquashfs pseudo definitions that give each path of a sysext tree
# its SELinux label, as the base policy's file contexts name it.
#
# systemd-sysext merges the sysext over /usr with overlayfs. A directory
# that is in the sysext and in the image shows the label of the top layer,
# the sysext. Without a label it is unlabeled_t: in the live session of
# albacore:gnome `ls -dZ /usr/lib64` gave unlabeled_t, and with enforcing=1
# systemd-resolved, systemd-logind and agetty could not load a library from
# /usr/lib64 ("Permission denied", run 45709421932).
#
# usage: selinux-pseudo.sh TREE   (paths relative to TREE, which is /)
set -euo pipefail
tree="${1:?usage: selinux-pseudo.sh TREE}"
label() {
	case "$1" in
	/usr/libexec | /usr/libexec/* | /usr/bin | /usr/bin/* | /usr/sbin | /usr/sbin/*) echo bin_t ;;
	/usr/lib | /usr/lib/* | /usr/lib64 | /usr/lib64/*) echo lib_t ;;
	/usr | /usr/*) echo usr_t ;;
	*) return 1 ;;
	esac
}
cd "${tree}"
find . -mindepth 1 | LC_ALL=C sort | while IFS= read -r rel; do
	path="${rel#.}"
	if type="$(label "${path}")"; then
		printf '%s x security.selinux=system_u:object_r:%s:s0\n' "${path}" "${type}"
	fi
done
