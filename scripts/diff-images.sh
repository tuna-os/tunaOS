#!/bin/bash
set -euo pipefail

BASE_IMAGE="$1"
TARGET_IMAGE="$2"
OUTPUT_FILE="${3:-diff_report.md}"

if [ -z "$BASE_IMAGE" ] || [ -z "$TARGET_IMAGE" ]; then
	echo "Usage: $0 <base_image> <target_image> [output_file]"
	exit 1
fi

echo "Diffing $BASE_IMAGE vs $TARGET_IMAGE..."

# Create temp dirs
TMPDIR=$(mktemp -d)
BASE_DIR="$TMPDIR/base"
TARGET_DIR="$TMPDIR/target"
mkdir -p "$BASE_DIR" "$TARGET_DIR"

# Function to extract info
extract_info() {
	local image="$1"
	local dir="$2"

	echo "Extracting info from $image..."

	# Run container to get RPM list and file list
	# We use 'podman run' with a volume or just cat the output

	# Get RPMs
	podman run --rm --entrypoint /bin/sh "$image" -c "rpm -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort" >"$dir/rpms.txt"

	# Get Files in /usr and /etc (excluding some noisy paths if needed)
	# We limit depth or exclude to avoid massive diffs if necessary, but user asked for /usr and /etc
	podman run --rm --entrypoint /bin/sh "$image" -c "find /usr /etc -xdev -type f | sort" >"$dir/files.txt"
}

extract_info "$BASE_IMAGE" "$BASE_DIR"
extract_info "$TARGET_IMAGE" "$TARGET_DIR"

# Generate Report
{
	echo "### Image Diff Report"
	echo ""
	echo "**Base Image:** \`$BASE_IMAGE\`"
	echo "**Target Image:** \`$TARGET_IMAGE\`"
	echo ""
} >"$OUTPUT_FILE"

# Diff RPMs
{
	echo "#### 📦 Package Changes"
	echo "\`\`\`diff"
	diff -u "$BASE_DIR/rpms.txt" "$TARGET_DIR/rpms.txt" | tail -n +3 || true
	echo "\`\`\`"
} >>"$OUTPUT_FILE"

# Diff Files
{
	echo "#### 📂 File Changes (/usr & /etc)"
	echo "\`\`\`diff"
	diff -u "$BASE_DIR/files.txt" "$TARGET_DIR/files.txt" | tail -n +3 || true
	echo "\`\`\`"
} >>"$OUTPUT_FILE"

echo "Report generated at $OUTPUT_FILE"

# Cleanup
rm -rf "$TMPDIR"
