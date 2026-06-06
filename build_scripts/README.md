# build_scripts/ — Container Image Build Scripts

Scripts in this directory run **inside the container** during `podman build`.
They are invoked by `RUN` instructions in the `Containerfile`.

These scripts install packages, configure services, and customize the OS image.
They run in the container's build context with access to `/run/context/`
(bind-mounted from the host's checkout).
