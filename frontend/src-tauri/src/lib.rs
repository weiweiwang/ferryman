#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rand::distributions::Alphanumeric;
use rand::{thread_rng, Rng};
use serde::Serialize;
use std::env;
use std::fs::OpenOptions;
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, RunEvent, State};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BackendConnection {
    ws_url: String,
    access_token: String,
}

struct BackendRuntime {
    child: Child,
    connection: BackendConnection,
}

#[derive(Default)]
struct BackendState {
    runtime: Mutex<Option<BackendRuntime>>,
}

fn random_token() -> String {
    thread_rng()
        .sample_iter(&Alphanumeric)
        .take(48)
        .map(char::from)
        .collect()
}

fn reserve_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    drop(listener);
    Ok(port)
}

fn home_dir() -> Option<PathBuf> {
    env::var_os("HOME").map(PathBuf::from)
}

fn legacy_root_dir() -> Option<PathBuf> {
    home_dir().map(|home| home.join(".ferryman"))
}

fn candidate_conda_paths() -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Some(home) = home_dir() {
        candidates.push(home.join("miniconda3/bin/conda"));
        candidates.push(home.join("anaconda3/bin/conda"));
        candidates.push(home.join("opt/miniconda3/bin/conda"));
    }

    candidates.push(PathBuf::from("/opt/homebrew/Caskroom/miniconda/base/bin/conda"));
    candidates.push(PathBuf::from("/usr/local/Caskroom/miniconda/base/bin/conda"));
    candidates
}

fn resolve_conda_executable() -> Result<PathBuf, String> {
    if let Ok(path) = env::var("CONDA_EXE") {
        let candidate = PathBuf::from(path);
        if candidate.exists() {
            return Ok(candidate);
        }
    }

    for candidate in candidate_conda_paths() {
        if candidate.exists() {
            return Ok(candidate);
        }
    }

    Err("Could not locate conda executable for Ferryman sidecar startup".to_string())
}

fn wait_for_backend(port: u16, timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    let addr = format!("127.0.0.1:{port}");

    while Instant::now() < deadline {
        if TcpStream::connect(&addr).is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(250));
    }

    Err(format!("Timed out waiting for backend on {addr}"))
}

fn bundled_backend_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        return Ok(manifest_dir.join("../../backend"));
    }

    let resource_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    let generated_backend = resource_dir.join("gen").join("backend");
    if generated_backend.exists() {
        return Ok(generated_backend);
    }

    let direct_backend = resource_dir.join("backend");
    if direct_backend.exists() {
        return Ok(direct_backend);
    }

    let nested_backend = resource_dir.join("_up_").join("_up_").join("backend");
    if nested_backend.exists() {
        return Ok(nested_backend);
    }

    Err(format!(
        "Bundled backend directory not found under {}",
        resource_dir.display()
    ))
}

fn bundled_backend_sidecar_executable(app: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        return Err("Bundled backend sidecar executable is only available in release builds".to_string());
    }

    let resource_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    let sidecar_dir = resource_dir.join("gen").join("backend-sidecar");
    let executable = sidecar_dir.join("ferryman");
    if executable.exists() {
        return Ok(executable);
    }

    Err(format!(
        "Bundled backend sidecar executable not found under {}",
        sidecar_dir.display()
    ))
}

fn bundled_skills_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        return Ok(manifest_dir.join("../../skills"));
    }

    let resource_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    let skills_dir = resource_dir.join("gen").join("skills");
    if skills_dir.exists() {
        return Ok(skills_dir);
    }

    Err(format!(
        "Bundled skills directory not found under {}",
        resource_dir.display()
    ))
}

fn backend_root_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(legacy_root) = legacy_root_dir() {
        return Ok(legacy_root);
    }

    let _ = app;
    Err("Could not resolve HOME for Ferryman root directory".to_string())
}

fn spawn_backend(app: &AppHandle) -> Result<BackendRuntime, String> {
    let port = reserve_port()?;
    let access_token = random_token();
    let ws_url = format!("ws://127.0.0.1:{port}/ws");
    let root_dir = backend_root_dir(app)?;
    let skills_dir = bundled_skills_dir(app)?;
    let ferryman_log = root_dir.join("user/logs/ferryman-tauri.log");
    if let Some(parent) = ferryman_log.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&ferryman_log)
        .map_err(|e| format!("Failed to open Ferryman sidecar log: {e}"))?;
    let stderr = stdout
        .try_clone()
        .map_err(|e| format!("Failed to clone Ferryman sidecar log handle: {e}"))?;

    let mut command = if cfg!(debug_assertions) {
        let backend_dir = bundled_backend_dir(app)?;
        if !backend_dir.exists() {
            return Err(format!("Backend directory not found: {}", backend_dir.display()));
        }

        let conda_exe = resolve_conda_executable()?;
        let mut command = Command::new(conda_exe);
        command
            .arg("run")
            .arg("-n")
            .arg("ferryman")
            .arg("python")
            .arg("-m")
            .arg("app.sidecar")
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .current_dir(&backend_dir);
        command
    } else {
        let sidecar_executable = bundled_backend_sidecar_executable(app)?;
        let mut command = Command::new(sidecar_executable);
        command
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string());
        command
    };

    let mut child = command
        .env("FERRYMAN_BEARER_TOKEN", &access_token)
        .env("FERRYMAN_ROOT_DIR", &root_dir)
        .env("FERRYMAN_BUNDLED_SKILLS_DIR", &skills_dir)
        .env("PYDANTIC_DISABLE_PLUGINS", "1")
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|e| format!("Failed to launch backend sidecar: {e}"))?;

    if let Err(e) = wait_for_backend(port, Duration::from_secs(20)) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(e);
    }

    Ok(BackendRuntime {
        child,
        connection: BackendConnection {
            ws_url,
            access_token,
        },
    })
}

fn ensure_backend_runtime(
    app: &AppHandle,
    state: &State<'_, BackendState>,
) -> Result<BackendConnection, String> {
    let mut runtime = state.runtime.lock().map_err(|_| "Backend state lock poisoned".to_string())?;

    if let Some(existing) = runtime.as_mut() {
        match existing.child.try_wait() {
            Ok(None) => return Ok(existing.connection.clone()),
            Ok(Some(_)) => {
                *runtime = None;
            }
            Err(e) => return Err(format!("Failed to inspect backend process: {e}")),
        }
    }

    let started = spawn_backend(app)?;
    let connection = started.connection.clone();
    *runtime = Some(started);
    Ok(connection)
}

fn cleanup_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        if let Ok(mut runtime) = state.runtime.lock() {
            if let Some(child_runtime) = runtime.as_mut() {
                let _ = child_runtime.child.kill();
                let _ = child_runtime.child.wait();
            }
            *runtime = None;
        }
    }
}

fn frontend_smoke_marker_path() -> Option<PathBuf> {
    env::var_os("FERRYMAN_FRONTEND_SMOKE_MARKER").map(PathBuf::from)
}

#[tauri::command]
fn get_backend_connection(
    app: AppHandle,
    state: State<'_, BackendState>,
) -> Result<BackendConnection, String> {
    ensure_backend_runtime(&app, &state)
}

#[tauri::command]
fn report_frontend_smoke_status(app: AppHandle, status: String) -> Result<(), String> {
    if let Some(marker_path) = frontend_smoke_marker_path() {
        if let Some(parent) = marker_path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create frontend smoke marker directory: {e}"))?;
        }

        let payload = format!("{{\"status\":\"{}\"}}", status.replace('"', "\\\""));
        std::fs::write(&marker_path, payload)
            .map_err(|e| format!("Failed to write frontend smoke marker: {e}"))?;

        if env::var("FERRYMAN_FRONTEND_SMOKE_AUTO_EXIT").as_deref() == Ok("1")
            && status == "backend_connected"
        {
            app.exit(0);
        }
    }

    Ok(())
}

#[tauri::command]
fn open_local_file(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open file: {}", e))?;
        return Ok(());
    }
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/C", "start", "", &path])
            .spawn()
            .map_err(|e| format!("Failed to open file: {}", e))?;
        return Ok(());
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("Failed to open file: {}", e))?;
        return Ok(());
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(BackendState::default())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            get_backend_connection,
            report_frontend_smoke_status,
            open_local_file
        ])
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            cleanup_backend(app_handle);
        }
    });
}
