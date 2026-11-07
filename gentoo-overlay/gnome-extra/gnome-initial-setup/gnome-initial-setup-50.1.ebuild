# Copyright 2026 TunaOS Authors
# Distributed under the terms of the GNU General Public License v2

# ::gentoo has no gnome-initial-setup ebuild (tunaOS#4426), and guppy:gnome
# needs it for the same first-boot account creation every other TunaOS GNOME
# image does. Same version line as the other variants (Fedora 44 ships 50.1).
# Kept to exactly what the image uses: no WebKit (privacy-policy viewer) and no
# malcontent (parental-controls pages), both optional upstream.

EAPI=8
inherit gnome.org meson xdg

DESCRIPTION="GNOME initial setup: first-boot account, language and keyboard"
HOMEPAGE="https://gitlab.gnome.org/GNOME/gnome-initial-setup"

LICENSE="GPL-2+"
SLOT="0"
KEYWORDS="~amd64"

DEPEND="
	>=dev-libs/glib-2.63.1:2
	>=gui-libs/gtk-4.17:4
	>=gui-libs/libadwaita-1.2:1
	gnome-base/gnome-desktop:4=
	>=gnome-base/gsettings-desktop-schemas-3.37.1
	>=gnome-base/gdm-3.8.3
	>=net-misc/networkmanager-1.2
	net-libs/libnma
	>=sys-auth/polkit-0.103
	sys-apps/accountsservice
	sci-geosciences/geocode-glib:2
	dev-libs/libgweather:4=
	>=app-misc/geoclue-2.6.0:2.0
	media-libs/fontconfig
	>=x11-libs/pango-1.32.5
	dev-libs/json-glib
	virtual/krb5
	>=app-crypt/libsecret-0.18.8
	dev-libs/libpwquality
	app-i18n/ibus
"
RDEPEND="${DEPEND}
	gnome-base/gnome-shell
"
BDEPEND="
	gnome-base/dconf
	dev-util/gdbus-codegen
	dev-util/glib-utils
	sys-devel/gettext
	virtual/pkgconfig
"

src_configure() {
	local emesonargs=(
		-Dibus=enabled
		-Dparental_controls=disabled
		-Dwebkitgtk=disabled
	)
	meson_src_configure
}
