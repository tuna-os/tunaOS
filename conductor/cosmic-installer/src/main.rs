use cosmic::iced::{
    self, widget::{column, container, text, button, progress_bar, checkbox, text_input},
    Length, Alignment, Sandbox, Settings,
};

pub fn main() -> iced::Result {
    CosmicInstaller::run(Settings::default())
}

#[derive(Debug, Clone)]
enum Message {
    StartInstall,
    ToggleBluetooth(bool),
    TogglePrinters(bool),
    PasswordChanged(String),
    Tick(usize),
    Finished(bool),
}

struct CosmicInstaller {
    step: usize,
    progress: f32,
    status: String,
    root_pwd: String,
    pair_bluetooth: bool,
    setup_printers: bool,
}

impl Sandbox for CosmicInstaller {
    type Message = Message;

    fn new() -> Self {
        Self {
            step: 0,
            progress: 0.0,
            status: String::from("Ready to install. Config details below:"),
            root_pwd: String::new(),
            pair_bluetooth: true,
            setup_printers: true,
        }
    }

    fn title(&self) -> String {
        String::from("TunaOS COSMIC Installer (bootc-installer Port)")
    }

    fn update(&mut self, message: Message) {
        match message {
            Message::StartInstall => {
                self.step = 1;
                self.progress = 10.0;
                self.status = String::from("Deploying system container using bootc-image-builder...");
            }
            Message::ToggleBluetooth(val) => {
                self.pair_bluetooth = val;
            }
            Message::TogglePrinters(val) => {
                self.setup_printers = val;
            }
            Message::PasswordChanged(pwd) => {
                self.root_pwd = pwd;
            }
            Message::Tick(pct) => {
                self.progress = pct as f32;
                if pct == 40 && self.pair_bluetooth {
                    self.status = String::from("Scanning nearby bluetooth keyboard and mice devices...");
                } else if pct == 70 && self.setup_printers {
                    self.status = String::from("Caching local networks CUPS printers...");
                }
            }
            Message::Finished(success) => {
                self.step = 2;
                self.progress = 100.0;
                if success {
                    self.status = String::from("TunaOS COSMIC successfully installed! Click below to reboot.");
                } else {
                    self.status = String::from("Installation failed.");
                }
            }
        }
    }

    fn view(&self) -> iced::Element<Message> {
        let content = match self.step {
            0 => column![
                text("TunaOS COSMIC Desktop Installer").size(30),
                text("Ported from projectbluefin/bootc-installer using iced-native widgets."),
                
                text_input("Enter Root Password", &self.root_pwd)
                    .on_input(Message::PasswordChanged)
                    .width(300),

                checkbox("Auto-pair bluetooth accessories", self.pair_bluetooth)
                    .on_toggle(Message::ToggleBluetooth),

                checkbox("Auto-configure CUPS network printers", self.setup_printers)
                    .on_toggle(Message::TogglePrinters),

                button("Install to /dev/vda").on_press(Message::StartInstall),
            ]
            .spacing(20)
            .align_items(Alignment::Center),
            1 => column![
                text(&self.status).size(20),
                progress_bar(0.0..=100.0, self.progress),
            ]
            .spacing(20)
            .align_items(Alignment::Center),
            _ => column![
                text(&self.status).size(24),
                button("Reboot system").on_press(Message::StartInstall),
            ]
            .spacing(20)
            .align_items(Alignment::Center),
        };

        container(content)
            .width(Length::Fill)
            .height(Length::Fill)
            .center_x()
            .center_y()
            .into()
    }
}
