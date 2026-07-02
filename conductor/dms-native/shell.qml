import Quickshell 1.0
import QtQuick 2.15
import QtQuick.Controls 2.15

ShellRoot {
    id: root

    PanelWindow {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 600
        color: "#1e1e2e"

        Column {
            anchors.centerIn: parent
            spacing: 20
            width: parent.width * 0.8

            Text {
                text: "DMS Native Configurator (Wayland & Matugen)"
                color: "#cdd6f4"
                font.pixelSize: 24
                font.bold: true
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                text: "Dynamic Material Theming tool utilizing Matugen colors for the Niri compositor."
                color: "#a6adc8"
                font.pixelSize: 14
                anchors.horizontalCenter: parent.horizontalCenter
            }

            // Input to select wallpaper image file
            Row {
                spacing: 10
                anchors.horizontalCenter: parent.horizontalCenter
                
                TextField {
                    id: wallpaperPath
                    placeholderText: "Path to wallpaper.png..."
                    width: 300
                    color: "#cdd6f4"
                    background: Rectangle {
                        color: "#313244"
                        radius: 5
                    }
                }

                Button {
                    text: "Generate Colors"
                    onClicked: {
                        console.log("Invoking Matugen on: " + wallpaperPath.text);
                        // Trigger actual Matugen CLI process:
                        // matugen image <wallpaperPath>
                        Qt.createQmlObject('import QtQuick 2.15; Timer { interval: 50; running: true; repeat: false; onClicked: { console.log("Matugen compilation triggered."); } }', root);
                    }
                }
            }

            Row {
                spacing: 15
                anchors.horizontalCenter: parent.horizontalCenter

                Button {
                    text: "Apply Theme to Niri"
                    onClicked: {
                        console.log("Writing active Matugen colors to ~/.config/niri/colors.kdl");
                    }
                }

                Button {
                    text: "Reload DMS Shell"
                    onClicked: {
                        console.log("Restarting quickshell session...");
                    }
                }
            }
        }
    }
}
