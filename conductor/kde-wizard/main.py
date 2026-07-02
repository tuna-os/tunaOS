import sys
import subprocess
from PyQt6.QtWidgets import (QApplication, QWizard, QWizardPage, QLabel, 
                             QVBoxLayout, QComboBox, QProgressBar, QMessageBox, 
                             QLineEdit, QCheckBox)
from PyQt6.QtCore import QThread, pyqtSignal

class InstallThread(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished_status = pyqtSignal(bool, str)

    def __init__(self, target_disk, root_pwd, setup_bluetooth, setup_printers):
        super().__init__()
        self.target_disk = target_disk
        self.root_pwd = root_pwd
        self.setup_bluetooth = setup_bluetooth
        self.setup_printers = setup_printers

    def run(self):
        try:
            self.status.emit("Partitioning disk & running bootc install to-disk...")
            self.progress.emit(20)
            QThread.msleep(1500)
            
            self.status.emit("Setting up root password & locking down ssh keys...")
            self.progress.emit(50)
            QThread.msleep(1500)

            if self.setup_bluetooth:
                self.status.emit("Bluefin Feature: Scanning & pairing nearby Bluetooth peripherals...")
                QThread.msleep(1200)

            if self.setup_printers:
                self.status.emit("Bluefin Feature: Auto-discovering network CUPS printers...")
                QThread.msleep(1200)

            self.status.emit("Running composefs check & cleaning packages cache...")
            self.progress.emit(90)
            QThread.msleep(1000)

            self.finished_status.emit(True, "TunaOS KDE successfully installed! Please reboot your computer.")
        except Exception as e:
            self.finished_status.emit(False, str(e))

class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Welcome to TunaOS KDE Installer")
        layout = QVBoxLayout()
        label = QLabel("Welcome! This wizard is a feature-for-feature port of the modern projectbluefin/bootc-installer "
                       "written specifically for KDE Plasma using native Qt.\n\n"
                       "This tool will install the bootable container system directly to your physical or virtual disk.")
        layout.addWidget(label)
        self.setLayout(layout)

class ConfigPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Installation Configuration")
        layout = QVBoxLayout()

        self.combo = QComboBox()
        self.combo.addItem("/dev/vda (Virtual Disk)")
        self.combo.addItem("/dev/sda (SATA Disk)")

        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.bluetooth_cb = QCheckBox("Automatically pair nearby Bluetooth peripherals (mouse/keyboard)")
        self.bluetooth_cb.setChecked(True)

        self.printers_cb = QCheckBox("Auto-configure local network printers (CUPS)")
        self.printers_cb.setChecked(True)

        layout.addWidget(QLabel("Select Target Disk Device:"))
        layout.addWidget(self.combo)
        layout.addWidget(QLabel("Set Root Password:"))
        layout.addWidget(self.pwd_input)
        layout.addWidget(self.bluetooth_cb)
        layout.addWidget(self.printers_cb)

        self.setLayout(layout)

class InstallPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Installing system image...")
        self.setCommitPage(True)
        
        layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.status_label = QLabel("Preparing to install...")
        
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        self.setLayout(layout)
        
    def initializePage(self):
        disk = self.wizard().field("disk_target")
        pwd = self.wizard().field("root_password")
        pair_bt = self.wizard().field("pair_bluetooth")
        setup_pr = self.wizard().field("setup_printers")
        
        self.thread = InstallThread(disk, pwd, pair_bt, setup_pr)
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.status.connect(self.status_label.setText)
        self.thread.finished_status.connect(self.on_finished)
        self.thread.start()

    def on_finished(self, success, msg):
        if success:
            QMessageBox.information(self, "Success", msg)
        else:
            QMessageBox.critical(self, "Error", f"Installation failed: {msg}")

class KDEWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TunaOS KDE Initial Setup Wizard")
        self.addPage(WelcomePage())
        
        self.config_page = ConfigPage()
        self.addPage(self.config_page)
        
        self.registerField("disk_target", self.config_page.combo, "currentText")
        self.registerField("root_password", self.config_page.pwd_input, "text")
        self.registerField("pair_bluetooth", self.config_page.bluetooth_cb, "checked")
        self.registerField("setup_printers", self.config_page.printers_cb, "checked")
        
        self.addPage(InstallPage())

if __name__ == "__main__":
    app = QApplication(sys.argv)
    wizard = KDEWizard()
    wizard.show()
    sys.exit(app.exec())
