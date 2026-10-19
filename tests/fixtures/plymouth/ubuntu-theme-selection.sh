# Selection functions from Ubuntu plymouth 24.004.60+git20250831.4a3c171d-0ubuntu8.
# Source: archive.ubuntu.com/ubuntu/pool/main/p/plymouth/
# These functions run against fixture directories, never the host /etc.
# $1: Configuration file
# $2: Setting name
function read_setting_from_file() {
	echo $(grep -v '^#' $1 2>/dev/null |
		awk '
                        BEGIN {
                        FS="[=[:space:]]+";
                        OFS="";
                        ORS=""
                     }
                     $1 ~/^'"$2"'$/ { print $2 }
               ')
}

# $1: Configuration file
function set_configured_theme_path_from_file() {
	CONFIGURED_THEME_DIR=$(read_setting_from_file "$1" "ThemeDir")
	CONFIGURED_THEME_NAME=$(read_setting_from_file "$1" "Theme")
}

function set_theme_dir() {
	set_configured_theme_path_from_file ${PLYMOUTH_CONFDIR}/plymouthd.conf
	if [ -z "$CONFIGURED_THEME_DIR" ] || [ ! -d "$CONFIGURED_THEME_DIR/$CONFIGURED_THEME_NAME" ]; then
		set_configured_theme_path_from_file ${PLYMOUTH_POLICYDIR}/plymouthd.defaults
	fi

	if [ -n "$CONFIGURED_THEME_DIR" ] && [ -d "$CONFIGURED_THEME_DIR/$CONFIGURED_THEME_NAME" ]; then
		PLYMOUTH_THEME_NAME=$CONFIGURED_THEME_NAME
		PLYMOUTH_THEME_DIR=$CONFIGURED_THEME_DIR/$CONFIGURED_THEME_NAME
	else
		PLYMOUTH_THEME_DIR=$PLYMOUTH_DATADIR/plymouth/themes/$PLYMOUTH_THEME_NAME
	fi
}
