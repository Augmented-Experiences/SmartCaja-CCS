// App de escritorio nativa SmartSuite (Tauri v2)
#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::io::{BufRead, Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Emitter, Manager, RunEvent, Url, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const OLLAMA_PORT: u16 = 11434;
const OLLAMA_HOST: &str = "127.0.0.1:11434";
const OLLAMA_API: &str = "http://127.0.0.1:11434";

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct Tier {
    max_ram_gb: f64,
    model: String,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct AppConfig {
    product_name: String,
    data_dir_name: String,
    ollama_tiers: Vec<Tier>,
    #[serde(default)]
    extra_models: Vec<String>,
}

static APP_CONFIG_JSON: &str = include_str!("../appconfig.json");

fn app_config() -> &'static AppConfig {
    static CFG: OnceLock<AppConfig> = OnceLock::new();
    CFG.get_or_init(|| serde_json::from_str(APP_CONFIG_JSON).expect("appconfig.json invalido"))
}

struct BackendState(Mutex<Option<CommandChild>>);
struct OllamaChild {
    pid: u32,
    child: Child,
}
struct OllamaState(Mutex<Option<OllamaChild>>);
struct ShutdownState(AtomicBool);
struct Navigated(Mutex<bool>);
struct LastProbe(Mutex<String>);

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct Status {
    phase: String,
    message: String,
    percent: i32,
    backend_url: Option<String>,
    can_continue: bool,
    ollama_done: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    backend_error: Option<String>,
}

impl Status {
    fn initial() -> Self {
        Status {
            phase: "starting".into(),
            message: "Iniciando servicios...".into(),
            percent: -1,
            backend_url: None,
            can_continue: false,
            ollama_done: false,
            backend_error: None,
        }
    }
}

struct AppStatus(Mutex<Status>);
struct BackendPort(u16);

fn persist_status_snapshot(snapshot: &Status) {
    let path = user_data_dir().join("desktop_status.json");
    if let Ok(json) = serde_json::to_string(snapshot) {
        let _ = std::fs::write(path, json);
    }
}

fn update_status(app: &tauri::AppHandle, f: impl FnOnce(&mut Status)) {
    let snapshot = {
        let state = app.state::<AppStatus>();
        let mut s = state.0.lock().unwrap();
        f(&mut s);
        s.clone()
    };
    persist_status_snapshot(&snapshot);
    let _ = app.emit("status", snapshot);
}

#[tauri::command]
fn current_status(state: tauri::State<AppStatus>) -> Status {
    state.0.lock().unwrap().clone()
}

#[tauri::command]
fn navigate_to_backend(
    app: tauri::AppHandle,
    port: tauri::State<BackendPort>,
) -> Result<(), String> {
    navigate_main_to_backend(&app, port.0)
}

#[tauri::command]
fn retry_backend(app: tauri::AppHandle, port: tauri::State<BackendPort>) -> Result<String, String> {
    let p = port.0;
    if try_mark_backend_ready(&app, p) {
        navigate_main_to_backend(&app, p)?;
        Ok(backend_app_url(p))
    } else {
        let detail = app.state::<LastProbe>().0.lock().unwrap().clone();
        Err(format!(
            "El servidor aun no responde con la UI. Diagnostico: {}",
            detail
        ))
    }
}

fn hidden_command(program: impl AsRef<std::ffi::OsStr>) -> Command {
    let mut cmd = Command::new(program);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

fn ollama_command() -> Command {
    hidden_command("ollama")
}

fn ollama_command_at(bin: &Path) -> Command {
    hidden_command(bin)
}

fn ollama_install_dir() -> PathBuf {
    user_data_dir().join("ollama")
}

fn ollama_runtime_dir() -> PathBuf {
    ollama_install_dir().join("runtime")
}

fn ollama_models_dir() -> PathBuf {
    ollama_install_dir().join("models")
}

fn ollama_download_dir() -> PathBuf {
    ollama_install_dir().join("download")
}

fn ollama_bin_name() -> &'static str {
    #[cfg(windows)]
    {
        "ollama.exe"
    }
    #[cfg(not(windows))]
    {
        "ollama"
    }
}

fn is_ollama_binary(path: &Path) -> bool {
    if !path.is_file() {
        return false;
    }
    path.file_name()
        .and_then(|n| n.to_str())
        .map(|n| n.eq_ignore_ascii_case(ollama_bin_name()))
        .unwrap_or(false)
}

fn find_portable_ollama(root: &Path) -> Option<PathBuf> {
    if !root.exists() {
        return None;
    }
    let preferred = [
        root.join(ollama_bin_name()),
        root.join("bin").join(ollama_bin_name()),
        root.join("Ollama").join(ollama_bin_name()),
    ];
    for p in preferred {
        if is_ollama_binary(&p) {
            return Some(p);
        }
    }
    fn walk(dir: &Path, depth: u8) -> Option<PathBuf> {
        if depth == 0 {
            return None;
        }
        let entries = std::fs::read_dir(dir).ok()?;
        let mut dirs = Vec::new();
        for ent in entries.flatten() {
            let p = ent.path();
            if is_ollama_binary(&p) {
                return Some(p);
            }
            if p.is_dir() {
                dirs.push(p);
            }
        }
        for d in dirs {
            if let Some(found) = walk(&d, depth - 1) {
                return Some(found);
            }
        }
        None
    }
    walk(root, 5)
}

fn ensure_unix_executable(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = std::fs::metadata(path) {
            let mut perms = meta.permissions();
            perms.set_mode(perms.mode() | 0o755);
            let _ = std::fs::set_permissions(path, perms);
        }
    }
    let _ = path;
}

fn binary_runs(bin: &Path) -> bool {
    ollama_command_at(bin)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn system_ollama_available() -> bool {
    ollama_command()
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn ollama_http_agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(30))
        .timeout_read(Duration::from_secs(6 * 3600))
        .timeout_write(Duration::from_secs(120))
        .user_agent("SmartCaja-CCS portable-ollama")
        .build()
}

fn ollama_http_healthy() -> bool {
    match ureq::get(&format!("{}/api/tags", OLLAMA_API))
        .timeout(Duration::from_secs(3))
        .call()
    {
        Ok(r) => r.status() == 200,
        Err(_) => false,
    }
}

fn official_ollama_archives() -> Vec<(&'static str, &'static str)> {
    // Official portable archives (zip / tgz). Current Linux latest is tar.zst;
    // tgz is tried first and skipped on 404. Never run the Windows system installer.
    let mut urls = Vec::new();
    if cfg!(all(windows, target_arch = "x86_64")) {
        urls.push((
            "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip",
            "ollama-windows-amd64.zip",
        ));
    } else if cfg!(all(windows, target_arch = "aarch64")) {
        urls.push((
            "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-arm64.zip",
            "ollama-windows-arm64.zip",
        ));
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        urls.push((
            "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tgz",
            "ollama-linux-amd64.tgz",
        ));
        urls.push((
            "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst",
            "ollama-linux-amd64.tar.zst",
        ));
    } else if cfg!(all(target_os = "linux", target_arch = "aarch64")) {
        urls.push((
            "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-arm64.tgz",
            "ollama-linux-arm64.tgz",
        ));
        urls.push((
            "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-arm64.tar.zst",
            "ollama-linux-arm64.tar.zst",
        ));
    } else if cfg!(target_os = "macos") {
        urls.push((
            "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz",
            "ollama-darwin.tgz",
        ));
    }
    urls
}

fn prepend_dir_to_path(dir: &Path) {
    let extra = dir.to_string_lossy().into_owned();
    let merged = match std::env::var_os("PATH") {
        Some(existing) => {
            let mut v = std::ffi::OsString::from(extra);
            #[cfg(windows)]
            v.push(";");
            #[cfg(not(windows))]
            v.push(":");
            v.push(existing);
            v
        }
        None => extra.into(),
    };
    std::env::set_var("PATH", merged);
}

fn apply_portable_env(bin: &Path) {
    if let Some(dir) = bin.parent() {
        prepend_dir_to_path(dir);
        if dir.file_name().and_then(|n| n.to_str()) == Some("bin") {
            if let Some(root) = dir.parent() {
                prepend_dir_to_path(root);
            }
        }
    }
    let models = ollama_models_dir();
    let _ = std::fs::create_dir_all(&models);
    std::env::set_var("OLLAMA_MODELS", models);
    std::env::set_var("OLLAMA_HOST", OLLAMA_HOST);
}

fn configure_serve_command(cmd: &mut Command, bin: Option<&Path>) {
    let models = ollama_models_dir();
    let _ = std::fs::create_dir_all(&models);
    if let Some(path) = bin {
        apply_portable_env(path);
    }
    cmd.arg("serve")
        .env("OLLAMA_HOST", OLLAMA_HOST)
        .env("OLLAMA_MODELS", models)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
}

fn record_owned_ollama(app: &tauri::AppHandle, child: Child) {
    let pid = child.id();
    let ollama_state = app.state::<OllamaState>();
    *ollama_state.0.lock().unwrap() = Some(OllamaChild { pid, child });
    ollama_log(&format!(
        "Ollama iniciado por SmartCaja (pid {}); se detendra al cerrar la app",
        pid
    ));
}

fn spawn_owned_ollama(app: &tauri::AppHandle, bin: Option<&Path>) -> bool {
    let mut cmd = match bin {
        Some(path) => ollama_command_at(path),
        None => ollama_command(),
    };
    configure_serve_command(&mut cmd, bin);
    match cmd.spawn() {
        Ok(child) => {
            record_owned_ollama(app, child);
            true
        }
        Err(e) => {
            ollama_log(&format!("No se pudo iniciar ollama serve: {}", e));
            false
        }
    }
}

fn wait_for_healthy_ollama(attempts: u32) -> bool {
    for _ in 0..attempts {
        if ollama_http_healthy() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn start_and_wait_ollama(app: &tauri::AppHandle, bin: Option<&Path>, message: &str) -> bool {
    update_status(app, |s| {
        s.phase = "ollama".into();
        s.message = message.into();
        s.percent = -1;
    });
    if !spawn_owned_ollama(app, bin) {
        return false;
    }
    let ok = wait_for_healthy_ollama(40);
    if ok {
        ollama_log(&format!(
            "Ollama HTTP API lista en 127.0.0.1:{}",
            OLLAMA_PORT
        ));
    } else {
        ollama_log("Ollama arranco pero /api/tags no respondio a tiempo");
    }
    ok
}

fn extract_archive(archive: &Path, dest: &Path) -> Result<(), String> {
    let _ = std::fs::create_dir_all(dest);
    let name = archive
        .file_name()
        .map(|s| s.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    let archive_s = archive.to_string_lossy().into_owned();
    let dest_s = dest.to_string_lossy().into_owned();

    let run = |mut cmd: Command| -> Result<(), String> {
        let status = cmd
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .status()
            .map_err(|e| format!("no se pudo extraer: {}", e))?;
        if status.success() {
            Ok(())
        } else {
            Err(format!("extractor salio con {}", status))
        }
    };

    if name.ends_with(".zip") {
        let tar = hidden_command("tar")
            .args(["-xf", &archive_s, "-C", &dest_s])
            .status();
        if tar.map(|s| s.success()).unwrap_or(false) {
            return Ok(());
        }
        #[cfg(windows)]
        {
            let script = format!(
                "Expand-Archive -LiteralPath '{}' -DestinationPath '{}' -Force",
                archive_s.replace('\'', "''"),
                dest_s.replace('\'', "''")
            );
            return run(hidden_command("powershell").args([
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                &script,
            ]));
        }
        #[cfg(not(windows))]
        {
            return Err("no hay extractor zip".into());
        }
    }

    if name.ends_with(".tar.zst") || name.ends_with(".tzst") {
        if run(hidden_command("tar").args(["--zstd", "-xf", &archive_s, "-C", &dest_s])).is_ok() {
            return Ok(());
        }
        let piped = format!(
            "zstd -dc '{}' | tar -xf - -C '{}'",
            archive_s.replace('\'', "'\\''"),
            dest_s.replace('\'', "'\\''")
        );
        return run(hidden_command("sh").args(["-c", &piped]));
    }

    if name.ends_with(".tgz") || name.ends_with(".tar.gz") {
        return run(hidden_command("tar").args(["-xzf", &archive_s, "-C", &dest_s]));
    }

    if name.ends_with(".tar") {
        return run(hidden_command("tar").args(["-xf", &archive_s, "-C", &dest_s]));
    }

    Err(format!("formato de archivo no soportado: {}", name))
}

fn download_url_with_progress(
    app: &tauri::AppHandle,
    url: &str,
    dest: &Path,
) -> Result<(), String> {
    if let Some(parent) = dest.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    ollama_log(&format!("Descargando {}", url));
    let resp = ollama_http_agent()
        .get(url)
        .call()
        .map_err(|e| format!("descarga Ollama: {}", e))?;
    if resp.status() >= 400 {
        return Err(format!("descarga Ollama HTTP {}", resp.status()));
    }
    let total = resp
        .header("Content-Length")
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(0);
    let mut reader = resp.into_reader();
    let tmp = dest.with_extension("partial");
    let mut file =
        std::fs::File::create(&tmp).map_err(|e| format!("no se pudo crear descarga: {}", e))?;
    let mut buf = [0u8; 64 * 1024];
    let mut copied: u64 = 0;
    let mut last_pct: i32 = -1;
    loop {
        let n = reader
            .read(&mut buf)
            .map_err(|e| format!("lectura descarga: {}", e))?;
        if n == 0 {
            break;
        }
        file.write_all(&buf[..n])
            .map_err(|e| format!("escritura descarga: {}", e))?;
        copied += n as u64;
        let pct: i32 = if total > 0 {
            ((copied.min(total) * 100) / total) as i32
        } else {
            -1
        };
        if pct != last_pct {
            last_pct = pct;
            let msg = if pct >= 0 {
                format!("Descargando Ollama (motor de IA) - {}%", pct)
            } else {
                format!(
                    "Descargando Ollama (motor de IA) - {} MB...",
                    copied / (1024 * 1024)
                )
            };
            update_status(app, |s| {
                s.phase = "downloading".into();
                s.message = msg;
                s.percent = pct;
            });
        }
    }
    drop(file);
    std::fs::rename(&tmp, dest).map_err(|e| format!("no se pudo finalizar descarga: {}", e))?;
    Ok(())
}

fn install_portable_ollama(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let archives = official_ollama_archives();
    if archives.is_empty() {
        return Err("no hay paquete portable de Ollama para esta plataforma".into());
    }
    let download_dir = ollama_download_dir();
    let runtime = ollama_runtime_dir();
    let _ = std::fs::create_dir_all(&download_dir);
    let mut last_err = String::from("sin intentos");
    for (url, filename) in archives {
        update_status(app, |s| {
            s.phase = "downloading".into();
            s.message = "Descargando Ollama (motor de IA portatil)...".into();
            s.percent = -1;
        });
        let archive = download_dir.join(filename);
        match download_url_with_progress(app, url, &archive) {
            Ok(()) => {
                update_status(app, |s| {
                    s.phase = "ollama".into();
                    s.message = "Extrayendo Ollama...".into();
                    s.percent = -1;
                });
                ollama_log(&format!("Extrayendo {} -> {}", archive.display(), runtime.display()));
                let _ = std::fs::remove_dir_all(&runtime);
                let _ = std::fs::create_dir_all(&runtime);
                match extract_archive(&archive, &runtime) {
                    Ok(()) => {
                        if let Some(bin) = find_portable_ollama(&runtime) {
                            ensure_unix_executable(&bin);
                            if binary_runs(&bin) {
                                let _ = std::fs::remove_file(&archive);
                                ollama_log(&format!("Ollama portable listo: {}", bin.display()));
                                return Ok(bin);
                            }
                            last_err = format!("binario extraido no ejecuta: {}", bin.display());
                        } else {
                            last_err = "el archivo no contiene el binario ollama".into();
                        }
                    }
                    Err(e) => last_err = e,
                }
            }
            Err(e) => {
                last_err = e;
                let _ = std::fs::remove_file(&archive);
            }
        }
    }
    Err(last_err)
}

fn home_dir() -> PathBuf {
    #[cfg(windows)]
    {
        std::env::var("USERPROFILE")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
    }
    #[cfg(not(windows))]
    {
        std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
    }
}

fn user_data_dir() -> PathBuf {
    let app = app_config().data_dir_name.as_str();
    #[cfg(target_os = "windows")]
    {
        let base = std::env::var("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home_dir().join("AppData").join("Roaming"));
        base.join(app)
    }
    #[cfg(target_os = "macos")]
    {
        home_dir()
            .join("Library")
            .join("Application Support")
            .join(app)
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let base = std::env::var("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home_dir().join(".local").join("share"));
        base.join(app)
    }
}

fn log_dir() -> PathBuf {
    let dir = user_data_dir().join("logs");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

fn ollama_log(line: &str) {
    let path = log_dir().join("ollama.log");
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = writeln!(f, "{}", line);
    }
}

/// Mismo archivo que los mensajes de Ollama (`logs/ollama.log` bajo APPDATA/SmartGastos).
fn backend_log(line: &str) {
    ollama_log(line);
}

fn kill_backend_child(app: &tauri::AppHandle) {
    let backend_state = app.state::<BackendState>();
    if let Some(child) = backend_state.0.lock().unwrap().take() {
        ollama_log("kill_backend_child: terminando sidecar backend");
        match child.kill() {
            Ok(()) => ollama_log("kill_backend_child: OK"),
            Err(e) => ollama_log(&format!("kill_backend_child: {}", e)),
        }
    }
}

fn kill_ollama_child(app: &tauri::AppHandle) {
    let ollama_state = app.state::<OllamaState>();
    if let Some(mut ollama) = ollama_state.0.lock().unwrap().take() {
        ollama_log(&format!(
            "kill_ollama_child: terminando Ollama iniciado por SmartCaja (pid {})",
            ollama.pid
        ));
        let pid = ollama.pid;
        match ollama.child.kill() {
            Ok(()) => {
                for _ in 0..10 {
                    match ollama.child.try_wait() {
                        Ok(Some(_)) => {
                            ollama_log("kill_ollama_child: OK");
                            break;
                        }
                        Ok(None) => std::thread::sleep(Duration::from_millis(100)),
                        Err(e) => {
                            ollama_log(&format!("kill_ollama_child: {}", e));
                            break;
                        }
                    }
                }
            }
            Err(e) => ollama_log(&format!("kill_ollama_child: {}", e)),
        }
        // Only the PID we spawned (never `taskkill ollama.exe` by name).
        #[cfg(windows)]
        {
            let _ = hidden_command("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
        #[cfg(unix)]
        {
            let _ = hidden_command("kill")
                .args(["-TERM", &format!("-{}", pid)])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
    }
}

fn shutdown_app(app: &tauri::AppHandle, reason: &str) {
    ollama_log(&format!("shutdown_app: {}", reason));
    kill_backend_child(app);
    std::thread::sleep(Duration::from_millis(200));
    kill_ollama_child(app);
}

fn shutdown_and_exit(app: &tauri::AppHandle, reason: &str) {
    let shutdown_state = app.state::<ShutdownState>();
    if shutdown_state.0.swap(true, Ordering::SeqCst) {
        return;
    }
    shutdown_app(app, reason);
    app.exit(0);
}

fn pick_port() -> u16 {
    for p in [7860u16, 7861, 7862, 7863] {
        if TcpListener::bind(("127.0.0.1", p)).is_ok() {
            return p;
        }
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(7860)
}

fn backend_app_url(port: u16) -> String {
    format!("http://127.0.0.1:{}/", port)
}

fn splash_url(port: u16) -> String {
    format!("http://127.0.0.1:{}/__splash/", port)
}

fn wait_for_health(port: u16, attempts: u32) -> bool {
    let health_url = format!("http://127.0.0.1:{}/api/health", port);
    for _ in 0..attempts {
        match ureq::get(&health_url).call() {
            Ok(r) if r.status() == 200 => {
                ollama_log("GET /api/health 200 — sidecar arriba");
                return true;
            }
            Ok(r) => ollama_log(&format!("GET /api/health status {}", r.status())),
            Err(e) => ollama_log(&format!("GET /api/health error: {}", e)),
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn navigate_webview_external(app: &tauri::AppHandle, url_str: &str) -> Result<(), String> {
    let parsed = Url::parse(url_str).map_err(|e| format!("URL invalida: {}", e))?;
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "ventana main no encontrada".to_string())?;
    window
        .navigate(parsed)
        .map_err(|e| format!("navigate fallo: {}", e))?;
    ollama_log(&format!("WebView navigate OK -> {}", url_str));
    Ok(())
}

fn open_splash_on_backend(app: &tauri::AppHandle, port: u16) {
    let url = splash_url(port);
    let handle = app.clone();
    ollama_log(&format!("abriendo splash same-origin: {}", url));
    match app.run_on_main_thread(move || {
        if let Some(w) = handle.get_webview_window("main") {
            let _ = w.show();
            let _ = w.set_focus();
        } else {
            ollama_log("open_splash_on_backend: ventana main no encontrada antes de navigate");
        }
        if let Err(e) = navigate_webview_external(&handle, &url) {
            ollama_log(&format!("open_splash_on_backend navigate: {}", e));
        }
    }) {
        Ok(()) => ollama_log("open_splash_on_backend: run_on_main_thread OK"),
        Err(e) => ollama_log(&format!("open_splash_on_backend: run_on_main_thread {}", e)),
    }
}

struct ProbeResult {
    ok: bool,
    detail: String,
}

fn probe_backend(port: u16) -> ProbeResult {
    let health_url = format!("http://127.0.0.1:{}/api/health", port);
    let root_url = backend_app_url(port);
    let health_status = match ureq::get(&health_url).call() {
        Ok(r) => r.status(),
        Err(e) => {
            return ProbeResult {
                ok: false,
                detail: format!("GET /api/health error: {}", e),
            };
        }
    };
    if health_status != 200 {
        return ProbeResult {
            ok: false,
            detail: format!("GET /api/health status {}", health_status),
        };
    }

    let ui_url = format!("http://127.0.0.1:{}/api/desktop-ui", port);
    if let Ok(r) = ureq::get(&ui_url).call() {
        if r.status() == 200 {
            if let Ok(body) = r.into_string() {
                ollama_log(&format!("/api/desktop-ui: {}", body));
                if body.contains("\"indexExists\":false") || body.contains("\"indexExists\": false")
                {
                    return ProbeResult {
                        ok: false,
                        detail: "sidecar sin app/index.html empaquetado (rebuild PyInstaller)"
                            .into(),
                    };
                }
            }
        }
    }

    match ureq::get(&root_url).call() {
        Ok(r) => {
            let status = r.status();
            let body = r.into_string().unwrap_or_default();
            let snippet: String = body.chars().take(120).collect();
            if status == 200 && (body.contains("<!DOCTYPE") || body.contains("<html")) {
                ProbeResult {
                    ok: true,
                    detail: "health 200 + HTML en /".into(),
                }
            } else {
                ProbeResult {
                    ok: false,
                    detail: format!("GET / status {} (no HTML). head={:?}", status, snippet),
                }
            }
        }
        Err(e) => ProbeResult {
            ok: false,
            detail: format!("GET / error: {}", e),
        },
    }
}

fn wait_for_backend_ready(app: &tauri::AppHandle, port: u16, attempts: u32) -> bool {
    for _ in 0..attempts {
        let probe = probe_backend(port);
        *app.state::<LastProbe>().0.lock().unwrap() = probe.detail.clone();
        if probe.ok {
            ollama_log(&format!("sidecar listo: {}", probe.detail));
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn apply_backend_ready(app: &tauri::AppHandle, port: u16) {
    let url = backend_app_url(port);
    update_status(app, |s| {
        s.backend_url = Some(url);
        s.can_continue = true;
        s.backend_error = None;
        s.phase = "ready".into();
        if s.ollama_done
            && (s.message.starts_with("Descargando") || s.message.starts_with("Componente"))
        {
            s.message = "Servicios listos.".into();
        }
    });
}

fn try_mark_backend_ready(app: &tauri::AppHandle, port: u16) -> bool {
    let probe = probe_backend(port);
    *app.state::<LastProbe>().0.lock().unwrap() = probe.detail.clone();
    ollama_log(&format!("probe try_mark_backend_ready: {}", probe.detail));
    if probe.ok {
        apply_backend_ready(app, port);
        true
    } else {
        false
    }
}

fn navigate_main_to_backend(app: &tauri::AppHandle, port: u16) -> Result<(), String> {
    if *app.state::<Navigated>().0.lock().unwrap() {
        return Ok(());
    }
    let probe = probe_backend(port);
    *app.state::<LastProbe>().0.lock().unwrap() = probe.detail.clone();
    ollama_log(&format!(
        "navigate_main_to_backend probe: ok={} {}",
        probe.ok, probe.detail
    ));
    if !probe.ok {
        update_status(app, |s| {
            s.phase = "warning".into();
            s.backend_error = Some(format!(
                "El servidor local no respondio: {}. Revise logs/ollama.log y reconstruya backend.exe.",
                probe.detail
            ));
        });
        ollama_log("navigate_main_to_backend: omitido (health/UI probe fallo)");
        return Err(probe.detail);
    }
    let _ = try_mark_backend_ready(app, port);
    let url_str = backend_app_url(port);
    navigate_webview_external(app, &url_str)?;
    *app.state::<Navigated>().0.lock().unwrap() = true;
    Ok(())
}

fn model_for_ram() -> String {
    let mut sys = sysinfo::System::new();
    sys.refresh_memory();
    let gb = sys.total_memory() as f64 / 1024.0 / 1024.0 / 1024.0;
    let cfg = app_config();
    for t in &cfg.ollama_tiers {
        if t.max_ram_gb > 0.0 && gb < t.max_ram_gb {
            return t.model.clone();
        }
    }
    cfg.ollama_tiers
        .last()
        .map(|t| t.model.clone())
        .unwrap_or_else(|| "llama3.2:3b".to_string())
}

fn pull_model_with_progress(app: &tauri::AppHandle, model: &str) -> bool {
    let body = format!("{{\"name\":\"{}\"}}", model);
    let resp = ureq::post(&format!("{}/api/pull", OLLAMA_API))
        .set("Content-Type", "application/json")
        .send_string(&body);
    let resp = match resp {
        Ok(r) => r,
        Err(_) => return false,
    };
    let reader = std::io::BufReader::new(resp.into_reader());
    let mut ok = false;
    for line in reader.lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }
        let v: serde_json::Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if v.get("error").is_some() {
            ok = false;
            break;
        }
        let status = v.get("status").and_then(|s| s.as_str()).unwrap_or("");
        let total = v.get("total").and_then(|t| t.as_u64());
        let completed = v.get("completed").and_then(|c| c.as_u64());
        let pct: i32 = match (total, completed) {
            (Some(t), Some(c)) if t > 0 => ((c.min(t) * 100) / t) as i32,
            _ => -1,
        };
        let msg = if pct >= 0 {
            format!("Descargando el modelo {} - {}%", model, pct)
        } else {
            format!("Preparando el modelo {} ({})...", model, status)
        };
        ollama_log(&msg);
        update_status(app, |s| {
            s.phase = "downloading".into();
            s.message = msg.clone();
            s.percent = pct;
        });
        if status == "success" {
            ok = true;
        }
    }
    ok
}

fn finish_ollama_bootstrap(app: &tauri::AppHandle, backend_port: u16) {
    ollama_log("== finish_ollama_bootstrap (post extra_models)");
    let _ = try_mark_backend_ready(app, backend_port);

    update_status(app, |s| {
        s.ollama_done = true;
        s.percent = 100;
        s.message = "Modelos listos. Abriendo la aplicacion...".into();
        if s.can_continue {
            s.phase = "ready".into();
            if s.backend_url.is_none() {
                s.backend_url = Some(backend_app_url(backend_port));
            }
        } else {
            let detail = app.state::<LastProbe>().0.lock().unwrap().clone();
            s.backend_error = Some(format!(
                "UI aun no lista: {}. Use Entrar en el splash.",
                detail
            ));
        }
    });
    ollama_log("ollama_done=true; splash debe hacer location.replace('/') via /api/desktop-status");
}

fn ensure_ollama_api(app: &tauri::AppHandle) -> bool {
    if ollama_http_healthy() {
        ollama_log("Ollama del sistema ya responde en :11434 (no se detendra al cerrar)");
        update_status(app, |s| {
            s.phase = "ollama".into();
            s.message = "Usando Ollama del sistema (ya en ejecucion).".into();
            s.percent = -1;
        });
        return true;
    }

    if let Some(bin) = find_portable_ollama(&ollama_runtime_dir()) {
        ensure_unix_executable(&bin);
        if binary_runs(&bin) {
            ollama_log(&format!("Arrancando Ollama portable existente: {}", bin.display()));
            return start_and_wait_ollama(
                app,
                Some(&bin),
                "Iniciando Ollama portable...",
            );
        }
    }

    if system_ollama_available() {
        ollama_log("Arrancando Ollama del PATH (la app lo detendra al cerrar)");
        return start_and_wait_ollama(app, None, "Iniciando el servicio de IA...");
    }

    update_status(app, |s| {
        s.phase = "downloading".into();
        s.message = "Ollama no esta instalado. Descargando motor de IA portatil...".into();
        s.percent = -1;
    });
    match install_portable_ollama(app) {
        Ok(bin) => start_and_wait_ollama(
            app,
            Some(&bin),
            "Iniciando el servicio de IA...",
        ),
        Err(e) => {
            ollama_log(&format!("No se pudo instalar Ollama portable: {}", e));
            update_status(app, |s| {
                s.phase = "warning".into();
                s.message =
                    "No se pudo descargar Ollama. La app abrira sin IA.".into();
                s.percent = -1;
            });
            false
        }
    }
}

fn pull_required_models(app: &tauri::AppHandle) {
    if !ollama_http_healthy() {
        ollama_log("Omitiendo pull: API Ollama no disponible");
        return;
    }
    let model = model_for_ram();
    update_status(app, |s| {
        s.phase = "downloading".into();
        s.message = format!("Descargando el modelo {} (solo la primera vez)...", model);
        s.percent = -1;
    });
    if pull_model_with_progress(app, &model) {
        update_status(app, |s| {
            s.message = format!("Modelo {} listo.", model);
            s.percent = 100;
        });
    }

    for extra in &app_config().extra_models {
        update_status(app, |s| {
            s.phase = "downloading".into();
            s.message = format!("Descargando componente de IA {}...", extra);
            s.percent = -1;
        });
        if pull_model_with_progress(app, extra) {
            ollama_log(&format!("Modelo adicional '{}' listo.", extra));
            update_status(app, |s| {
                s.message = format!("Componente {} listo.", extra);
                s.percent = 100;
            });
        }
    }
}

fn bootstrap_ollama(app: tauri::AppHandle, backend_port: u16) {
    std::thread::spawn(move || {
        update_status(&app, |s| {
            s.phase = "ollama".into();
            s.message = "Verificando el motor de IA (Ollama)...".into();
            s.percent = -1;
        });
        ollama_log(&format!(
            "== {}: bootstrap Ollama portable (sin MSI, sin reinicio) ==",
            app_config().product_name
        ));

        let _ = ensure_ollama_api(&app);
        pull_required_models(&app);

        ollama_log("bootstrap Ollama terminado; la app continua sin reiniciar");
        finish_ollama_bootstrap(&app, backend_port);
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState(Mutex::new(None)))
        .manage(OllamaState(Mutex::new(None)))
        .manage(ShutdownState(AtomicBool::new(false)))
        .manage(AppStatus(Mutex::new(Status::initial())))
        .manage(Navigated(Mutex::new(false)))
        .manage(LastProbe(Mutex::new(String::new())))
        .invoke_handler(tauri::generate_handler![
            current_status,
            retry_backend,
            navigate_to_backend
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            *handle.state::<Navigated>().0.lock().unwrap() = false;
            persist_status_snapshot(&Status::initial());

            if let Some(w) = handle.get_webview_window("main") {
                let app_for_window = handle.clone();
                w.on_window_event(move |event| {
                    match event {
                        WindowEvent::CloseRequested { .. } => {
                            shutdown_and_exit(&app_for_window, "ventana main CloseRequested");
                        }
                        WindowEvent::Destroyed => {
                            shutdown_and_exit(&app_for_window, "ventana main Destroyed");
                        }
                        _ => {}
                    }
                });
            }

            kill_backend_child(&handle);
            let port = pick_port();
            app.manage(BackendPort(port));
            ollama_log(&format!("Puerto backend elegido: {}", port));

            let data_dir = user_data_dir().to_string_lossy().to_string();
            let ollama_models = ollama_models_dir().to_string_lossy().to_string();
            let backend_state = app.state::<BackendState>();
            if backend_state.0.lock().unwrap().is_some() {
                ollama_log("WARN: sidecar ya registrado; omitiendo segundo spawn");
            }
            let sidecar = app.shell().sidecar("backend");
            match sidecar {
                Ok(cmd) => match cmd
                    .env("PORT", port.to_string())
                    .env("DATA_DIR", data_dir)
                    .env("RUN_BY_TAURI", "1")
                    .env("PYTHONIOENCODING", "utf-8")
                    .env("OLLAMA_URL", OLLAMA_API)
                    .env("OLLAMA_HOST", OLLAMA_HOST)
                    .env("OLLAMA_MODELS", ollama_models)
                    .spawn()
                {
                    Ok((mut rx, child)) => {
                        let backend_state = app.state::<BackendState>();
                        let mut slot = backend_state.0.lock().unwrap();
                        if slot.is_some() {
                            ollama_log("WARN: sidecar slot ocupado; matando instancia duplicada");
                            let _ = slot.take().map(|c| c.kill());
                        }
                        slot.replace(child);
                        let sidecar_handle = handle.clone();
                        tauri::async_runtime::spawn(async move {
                            while let Some(event) = rx.recv().await {
                                if let CommandEvent::Stderr(bytes) | CommandEvent::Stdout(bytes) =
                                    event
                                {
                                    backend_log(&String::from_utf8_lossy(&bytes));
                                }
                            }
                            ollama_log("sidecar backend: canal de eventos cerrado (proceso terminó?)");
                            shutdown_and_exit(&sidecar_handle, "sidecar stdout/stderr EOF");
                        });
                    }
                    Err(e) => {
                        backend_log(&format!("spawn error: {}", e));
                        update_status(&handle, |s| {
                            s.phase = "warning".into();
                            s.message = format!("No se pudo iniciar el servidor: {}", e);
                            s.backend_error = Some(s.message.clone());
                        });
                    }
                },
                Err(e) => {
                    backend_log(&format!("sidecar missing: {}", e));
                    update_status(&handle, |s| {
                        s.phase = "warning".into();
                        s.message = format!("Backend no encontrado en el instalador: {}", e);
                        s.backend_error = Some(s.message.clone());
                    });
                }
            }

            let splash_handle = handle.clone();
            std::thread::spawn(move || {
                if wait_for_health(port, 120) {
                    open_splash_on_backend(&splash_handle, port);
                } else {
                    ollama_log(
                        "ERROR: /api/health no respondio; sidecar caido (revise traceback en este log)",
                    );
                    update_status(&splash_handle, |s| {
                        s.phase = "warning".into();
                        s.message = "El servidor local no inicio.".into();
                        s.backend_error = Some(
                            "El sidecar (backend.exe) termino antes de escuchar. \
                             Reconstruya con build-backend.ps1 y revise logs/ollama.log."
                                .into(),
                        );
                    });
                }
            });

            bootstrap_ollama(handle.clone(), port);

            let ready_handle = handle.clone();
            std::thread::spawn(move || {
                if wait_for_backend_ready(&ready_handle, port, 3600) {
                    apply_backend_ready(&ready_handle, port);
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir la app de escritorio")
        .run(|app_handle, event| {
            match event {
                RunEvent::ExitRequested { .. } => {
                    shutdown_and_exit(app_handle, "RunEvent::ExitRequested");
                }
                RunEvent::Exit => {
                    shutdown_and_exit(app_handle, "RunEvent::Exit");
                }
                RunEvent::WindowEvent { label, event, .. } if label == "main" => {
                    if matches!(event, WindowEvent::CloseRequested { .. }) {
                        shutdown_and_exit(app_handle, "RunEvent::WindowEvent CloseRequested");
                    }
                    if matches!(event, WindowEvent::Destroyed) {
                        shutdown_and_exit(app_handle, "RunEvent::WindowEvent Destroyed");
                    }
                }
                _ => {}
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_ollama_in_bin_subdir() {
        let dir = std::env::temp_dir().join(format!(
            "smartcaja-ollama-find-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let runtime = dir.join("runtime");
        let bin_dir = runtime.join("bin");
        std::fs::create_dir_all(&bin_dir).unwrap();
        std::fs::create_dir_all(runtime.join("lib").join("ollama")).unwrap();
        let bin = bin_dir.join(ollama_bin_name());
        std::fs::write(&bin, b"fake-ollama").unwrap();
        let found = find_portable_ollama(&runtime).expect("debe encontrar binario");
        assert_eq!(found, bin);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn official_archives_are_portable_not_msi() {
        let urls = official_ollama_archives();
        assert!(
            !urls.is_empty(),
            "esta plataforma debe tener zip/tgz/tar.zst"
        );
        for (url, name) in urls {
            let lower = format!("{} {}", url, name).to_lowercase();
            assert!(!lower.contains("ollamasetup"), "{}", name);
            assert!(!lower.contains(".msi"), "{}", name);
            assert!(
                name.ends_with(".zip")
                    || name.ends_with(".tgz")
                    || name.ends_with(".tar.zst")
                    || name.ends_with(".tar.gz"),
                "{}",
                name
            );
        }
    }
}
