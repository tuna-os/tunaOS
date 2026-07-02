import Quickshell 1.0
import QtQuick 2.15
import QtQuick.Controls 2.15

ShellRoot {
    id: root

    PanelWindow {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 480
        color: "#1e1e2e"

        Column {
            anchors.centerIn: parent
            spacing: 20

            Text {
                text: "DankMaterialShell (DMS) Native Configurator"
                color: "#cdd6f4"
                font.pixelSize: 24
                font.bold: true
            }

            Text {
                text: "Configure settings, theme setups, and Niri window shortcuts."
                color: "#a6adc8"
                font.pixelSize: 16
            }

            Row {
                spacing: 15
                anchors.horizontalCenter: parent.horizontalCenter

                Button {
                    text: "Reload Shell"
                    onClicked: {
                        console.log("Reloading quickshell configurations...");
                    }
                }

                Button {
                    text: "Material Theming (Matugen)"
                    onClicked: {
                        console.log("Applying Matugen colors...");
                    }
                }
            }
        }
    }
}
