#!/usr/bin/env python3
"""Generate Containerfile, Containerfile.hwe, and Containerfile.nvidia from templates.

Desktop stages are generated from a single list — adding a new desktop
environment requires editing only this script, not three Containerfiles.

Templates live alongside their output files:
  Containerfile.template      → Containerfile
  Containerfile.hwe.template  → Containerfile.hwe
  Containerfile.nvidia.template → Containerfile.nvidia

Usage:
  python3 scripts/generate-containerfiles.py
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Desktop environments with their build script (none means no script — HWE/NVIDIA only)
DESKTOPS = [
    {"name": "gnome",   "script": "gnome.sh"},
    {"name": "cosmic",  "script": "cosmic.sh"},
    {"name": "gnome50", "script": "gnome.sh"},     # uses gnome.sh
    {"name": "kde",     "script": "kde.sh"},
    {"name": "niri",    "script": "niri.sh"},
]

SHARED_CONTEXT = """FROM scratch as context
COPY system_files /files
COPY --from=brew /system_files /files
COPY --from=common /system_files/shared /files
COPY system_files_overrides /overrides
COPY build_scripts /build_scripts"""

MOUNT_PREAMBLE = (
    "RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \\\n"
    "  --mount=type=tmpfs,dst=/boot \\\n"
    "  --mount=type=bind,from=context,source=/,target=/run/context"
)


def generate_main_stages() -> str:
    """Generate DE stages for Containerfile (runs build scripts + versionlock + symlink)."""
    stages = []
    for de in DESKTOPS:
        stage_name = de["name"]
        script = de["script"]

        stages.append(f"FROM base-no-de AS {stage_name}")
        stages.append(f"{MOUNT_PREAMBLE} \\")
        stages.append(f"  /run/context/build_scripts/{script} base")
        stages.append("RUN dnf versionlock add glib2")
        stages.append("RUN rm -rf /opt && ln -s /var/opt /opt")

    return "\n\n".join(stages) + "\n"


def generate_light_stages(base_image: str, file_desc: str) -> str:
    """Generate DE stages for HWE/NVIDIA Containerfiles (env-only — no build scripts)."""
    stages = []

    for i, de in enumerate(DESKTOPS):
        name = de["name"]
        stages.append(f"# {'='*60}")
        stages.append(f"# {name.upper()} variant - {base_image} base "
                      f"with {name.upper()} desktop target")
        stages.append(f"# {'='*60}")
        stages.append(f"FROM {base_image} AS {name}")
        stages.append("")
        stages.append(f"ARG DESKTOP_FLAVOR={name}")
        stages.append(f"ENV DESKTOP_FLAVOR={name}")
        stages.append("")
        stages.append("# Lock glib2 for consistency")
        stages.append("RUN dnf versionlock add glib2")
        stages.append("")

        # Last desktop (niri) in hwe gets extra comment
        comment = "RUN rm -rf /opt && ln -s /var/opt /opt"
        if name == "niri" and file_desc == "hwe":
            comment += " "
        stages.append(comment)

        if i < len(DESKTOPS) - 1:
            stages.append("")

    return "\n".join(stages) + "\n"


def process_template(template_path: str, output_path: str, de_stages: str, context: str = "") -> None:
    """Read template, replace placeholders, write output."""
    with open(template_path) as f:
        content = f.read()

    content = content.replace("{{CONTEXT}}", context)
    content = content.replace("{{DE_STAGES}}", de_stages)

    with open(output_path, "w") as f:
        f.write(content)

    print(f"  {os.path.basename(output_path)} ({len(content.splitlines())} lines)")


def main():
    os.chdir(REPO_ROOT)

    print("Generating Containerfiles...")

    process_template(
        "Containerfile.template",
        "Containerfile",
        generate_main_stages(),
    )
    process_template(
        "Containerfile.hwe.template",
        "Containerfile.hwe",
        generate_light_stages("base-hwe", "hwe"),
        context=SHARED_CONTEXT,
    )
    process_template(
        "Containerfile.nvidia.template",
        "Containerfile.nvidia",
        generate_light_stages("base-nvidia", "nvidia"),
        context=SHARED_CONTEXT,
    )

    print("Done.")


if __name__ == "__main__":
    main()
