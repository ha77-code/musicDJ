use std::{
    env,
    fs::{create_dir_all, OpenOptions},
    io::{Read, Write},
    net::{TcpStream, ToSocketAddrs},
    path::{Path, PathBuf},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const BACKEND_PORT: u16 = 18765;
const NETEASE_PORT: u16 = 13000;

struct SidecarState {
    children: Mutex<Vec<CommandChild>>,
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState {
            children: Mutex::new(Vec::new()),
        })
        .setup(|app| {
            let app_handle = app.handle().clone();
            let app_data = resolve_app_data_dir(&app_handle);
            let resource_dir = resolve_resource_dir(&app_handle);
            let logs_dir = app_data.join("logs");
            create_dir_all(&logs_dir)?;

            write_log(
                &logs_dir.join("tauri.log"),
                &format!(
                    "starting Music DJ app_data={} resource={}",
                    app_data.display(),
                    resource_dir.display()
                ),
            );

            let netease_child = spawn_sidecar(
                &app_handle,
                "netease-api",
                &logs_dir.join("netease-api.log"),
                vec![
                    ("PORT", NETEASE_PORT.to_string()),
                    ("HOST", "127.0.0.1".to_string()),
                    ("NODE_ENV", "production".to_string()),
                    ("NCM_API_CHECK_VERSION", "false".to_string()),
                    ("NCM_API_SKIP_ANONYMOUS_TOKEN", "true".to_string()),
                ],
            )?;
            app.state::<SidecarState>()
                .children
                .lock()
                .expect("sidecar lock")
                .push(netease_child);

            let backend_child = spawn_sidecar(
                &app_handle,
                "musicdj-backend",
                &logs_dir.join("backend.log"),
                vec![
                    ("MUSICDJ_APP_DATA", app_data.to_string_lossy().to_string()),
                    (
                        "MUSICDJ_RESOURCE_DIR",
                        resource_dir.to_string_lossy().to_string(),
                    ),
                    ("MUSICDJ_PORT", BACKEND_PORT.to_string()),
                    (
                        "MUSICDJ_NETEASE_API_HOST",
                        format!("http://127.0.0.1:{NETEASE_PORT}"),
                    ),
                ],
            )?;
            app.state::<SidecarState>()
                .children
                .lock()
                .expect("sidecar lock")
                .push(backend_child);

            if !wait_for_backend(BACKEND_PORT, Duration::from_secs(45)) {
                write_log(
                    &logs_dir.join("tauri.log"),
                    "backend did not become ready before timeout",
                );
            }

            WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::External(Url::parse(&format!(
                    "http://127.0.0.1:{BACKEND_PORT}/"
                ))?),
            )
            .title("Music DJ")
            .inner_size(1220.0, 820.0)
            .min_inner_size(900.0, 650.0)
            .build()?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                stop_sidecars(window.app_handle());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Music DJ desktop app");
}

fn resolve_app_data_dir(app: &AppHandle) -> PathBuf {
    if let Some(app_data) = env::var_os("MUSICDJ_APP_DATA") {
        return PathBuf::from(app_data);
    }
    if let Some(roaming) = env::var_os("APPDATA") {
        return PathBuf::from(roaming).join("Music DJ");
    }
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from(".").join("Music DJ"))
}

fn resolve_resource_dir(app: &AppHandle) -> PathBuf {
    if let Some(resource_dir) = env::var_os("MUSICDJ_RESOURCE_DIR") {
        return PathBuf::from(resource_dir);
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        if resource_dir.join("frontend").exists() {
            return resource_dir;
        }
    }
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .to_path_buf()
}

fn spawn_sidecar(
    app: &AppHandle,
    name: &str,
    log_path: &Path,
    envs: Vec<(&str, String)>,
) -> Result<CommandChild, Box<dyn std::error::Error>> {
    let mut command = app.shell().sidecar(name)?;
    for (key, value) in envs {
        command = command.env(key, value);
    }
    let (mut rx, child) = command.spawn()?;
    let log = log_path.to_path_buf();
    let label = name.to_string();
    thread::spawn(move || {
        while let Some(event) = rx.blocking_recv() {
            let line = match event {
                CommandEvent::Stdout(bytes) => String::from_utf8_lossy(&bytes).to_string(),
                CommandEvent::Stderr(bytes) => String::from_utf8_lossy(&bytes).to_string(),
                CommandEvent::Terminated(_) => format!("{label} terminated\n"),
                _ => format!("{label} event\n"),
            };
            write_log(&log, line.trim_end());
        }
    });
    Ok(child)
}

fn wait_for_backend(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if check_http_status(port) {
            return true;
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}

fn check_http_status(port: u16) -> bool {
    let addr = match ("127.0.0.1", port).to_socket_addrs() {
        Ok(mut addrs) => match addrs.next() {
            Some(addr) => addr,
            None => return false,
        },
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(400)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.write_all(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    let mut body = String::new();
    if stream.read_to_string(&mut body).is_ok() {
        return body.contains("200 OK") && body.contains("\"running\"");
    }
    false
}

fn stop_sidecars(app: &AppHandle) {
    let state = app.state::<SidecarState>();
    {
        let Ok(mut children) = state.children.lock() else {
            return;
        };
        for child in children.drain(..) {
            let _ = child.kill();
        }
    }
}

fn write_log(path: &Path, message: &str) {
    if let Some(parent) = path.parent() {
        let _ = create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{message}");
    }
}
