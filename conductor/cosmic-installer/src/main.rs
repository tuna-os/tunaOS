// TunaOS COSMIC installer — port of projectbluefin/bootc-installer onto
// libcosmic. Ported against the `Sandbox` trait, which current libcosmic no
// longer exposes (superseded by `Application` — Sandbox was iced 0.9-era);
// that mismatch is exactly the kind of drift `cargo check` in CI now catches
// (tuna-os/tunaos#577) instead of leaving this port to silently rot unbuilt.
use cosmic::app::{Core, Task};
use cosmic::iced::alignment::{Horizontal, Vertical};
use cosmic::iced::{Alignment, Length};
use cosmic::widget::{
    button, checkbox, container, determinate_linear, text, text_input, Column,
};
use cosmic::{Application, Element};

fn main() -> cosmic::iced::Result {
    let settings = cosmic::app::Settings::default();
    cosmic::app::run::<CosmicInstaller>(settings, ())
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
    core: Core,
    step: usize,
    progress: f32,
    status: String,
    root_pwd: String,
    pair_bluetooth: bool,
    setup_printers: bool,
}

impl Application for CosmicInstaller {
    type Executor = cosmic::executor::Default;
    type Flags = ();
    type Message = Message;

    const APP_ID: &'static str = "org.tunaos.CosmicInstaller";

    fn core(&self) -> &Core {
        &self.core
    }

    fn core_mut(&mut self) -> &mut Core {
        &mut self.core
    }

    fn init(core: Core, _flags: Self::Flags) -> (Self, Task<Self::Message>) {
        let app = Self {
            core,
            step: 0,
            progress: 0.0,
            status: String::from("Ready to install. Config details below:"),
            root_pwd: String::new(),
            pair_bluetooth: true,
            setup_printers: true,
        };
        (app, Task::none())
    }

    fn update(&mut self, message: Self::Message) -> Task<Self::Message> {
        match message {
            Message::StartInstall => {
                self.step = 1;
                self.progress = 10.0;
                self.status =
                    String::from("Deploying system container using bootc-image-builder...");
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
                self.status = if success {
                    String::from("TunaOS COSMIC successfully installed! Click below to reboot.")
                } else {
                    String::from("Installation failed.")
                };
            }
        }
        Task::none()
    }

    fn view(&self) -> Element<'_, Self::Message> {
        let content: Element<_> = match self.step {
            0 => Column::new()
                .push(text("TunaOS COSMIC Desktop Installer").size(30))
                .push(text(
                    "Ported from projectbluefin/bootc-installer using iced-native widgets.",
                ))
                .push(
                    text_input("Enter Root Password", &self.root_pwd)
                        .on_input(Message::PasswordChanged)
                        .width(300),
                )
                .push(
                    checkbox(self.pair_bluetooth)
                        .label("Auto-pair bluetooth accessories")
                        .on_toggle(Message::ToggleBluetooth),
                )
                .push(
                    checkbox(self.setup_printers)
                        .label("Auto-configure CUPS network printers")
                        .on_toggle(Message::TogglePrinters),
                )
                .push(button::suggested("Install to /dev/vda").on_press(Message::StartInstall))
                .spacing(20)
                .align_x(Alignment::Center)
                .into(),
            1 => Column::new()
                .push(text(self.status.clone()).size(20))
                .push(determinate_linear(self.progress / 100.0))
                .spacing(20)
                .align_x(Alignment::Center)
                .into(),
            _ => Column::new()
                .push(text(self.status.clone()).size(24))
                .push(button::suggested("Reboot system").on_press(Message::StartInstall))
                .spacing(20)
                .align_x(Alignment::Center)
                .into(),
        };

        container(content)
            .width(Length::Fill)
            .height(Length::Fill)
            .align_x(Horizontal::Center)
            .align_y(Vertical::Center)
            .into()
    }
}
