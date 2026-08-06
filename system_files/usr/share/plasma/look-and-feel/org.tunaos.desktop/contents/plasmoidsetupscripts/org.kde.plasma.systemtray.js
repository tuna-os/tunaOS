const systemtrayId = applet.readConfig("SystrayContainmentId");
if (systemtrayId) {
    const systrayContainer = desktopById(systemtrayId);
    if (systrayContainer) {
        systrayContainer.currentConfigGroup = ["General"];
        systrayContainer.writeConfig("scaleIconsToFit", true);
    }
}
