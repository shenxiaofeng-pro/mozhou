use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use tauri::{Manager, State};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

const SIDECAR_STARTUP_TIMEOUT: Duration = Duration::from_secs(10);
const HEALTH_REQUEST_TIMEOUT: Duration = Duration::from_millis(300);

struct ApiSidecar {
    base_url: String,
    child: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn api_base_url(sidecar: State<'_, ApiSidecar>) -> String {
    sidecar.base_url.clone()
}

fn select_loopback_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0))?;
    Ok(listener.local_addr()?.port())
}

fn is_healthy_http_response(response: &[u8]) -> bool {
    let response = String::from_utf8_lossy(response);
    response.starts_with("HTTP/1.1 200") && response.contains(r#"{"status":"ok"}"#)
}

fn wait_for_health(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect_timeout(&address.into(), HEALTH_REQUEST_TIMEOUT) {
            let _ = stream.set_read_timeout(Some(HEALTH_REQUEST_TIMEOUT));
            let _ = stream.set_write_timeout(Some(HEALTH_REQUEST_TIMEOUT));
            if stream
                .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                .is_ok()
            {
                let mut response = [0_u8; 1024];
                if let Ok(length) = stream.read(&mut response)
                    && is_healthy_http_response(&response[..length])
                {
                    return true;
                }
            }
        }
        sleep(Duration::from_millis(100));
    }
    false
}

fn start_api_sidecar(app: &tauri::App) -> Result<ApiSidecar, String> {
    let port = select_loopback_port().map_err(|error| format!("无法选择本地 API 端口：{error}"))?;
    let command = app
        .shell()
        .sidecar("mozhou-api")
        .map_err(|error| format!("无法定位本地 API：{error}"))?
        .args(["--port", &port.to_string()]);
    let (mut events, child) = command
        .spawn()
        .map_err(|error| format!("无法启动本地 API：{error}"))?;
    tauri::async_runtime::spawn(async move { while events.recv().await.is_some() {} });

    if !wait_for_health(port, SIDECAR_STARTUP_TIMEOUT) {
        let _ = child.kill();
        return Err("本地 API 未能在限定时间内完成健康检查".to_owned());
    }

    Ok(ApiSidecar {
        base_url: format!("http://127.0.0.1:{port}"),
        child: Mutex::new(Some(child)),
    })
}

fn stop_api_sidecar(app: &tauri::AppHandle) {
    let sidecar = app.state::<ApiSidecar>();
    if let Ok(mut child) = sidecar.child.lock()
        && let Some(child) = child.take()
    {
        let _ = child.kill();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let application = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![api_base_url])
        .setup(|app| {
            let sidecar = start_api_sidecar(app).map_err(std::io::Error::other)?;
            app.manage(sidecar);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Mozhou desktop application");
    application.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            stop_api_sidecar(app);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{is_healthy_http_response, select_loopback_port};

    #[test]
    fn selects_a_nonzero_loopback_port() {
        assert!(select_loopback_port().expect("port should be available") > 0);
    }

    #[test]
    fn accepts_only_the_expected_health_response() {
        assert!(is_healthy_http_response(
            b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"status\":\"ok\"}"
        ));
        assert!(!is_healthy_http_response(
            b"HTTP/1.1 503 Service Unavailable\r\n\r\n{\"status\":\"starting\"}"
        ));
    }
}
