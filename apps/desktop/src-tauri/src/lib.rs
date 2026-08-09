use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{Manager, State};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

mod credentials;

use credentials::{
    CredentialStatus, SystemCredentialStore, activate_saved, credential_status, delete_credential,
    restore_active_profile, store_and_activate,
};

const SIDECAR_STARTUP_TIMEOUT: Duration = Duration::from_secs(10);
const HEALTH_REQUEST_TIMEOUT: Duration = Duration::from_millis(300);
const SESSION_TOKEN_ENV: &str = "MOZHOU_API_SESSION_TOKEN";

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ApiConnection {
    base_url: String,
    session_token: String,
}

struct ApiSidecar {
    connection: ApiConnection,
    child: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn api_connection(sidecar: State<'_, ApiSidecar>) -> ApiConnection {
    sidecar.connection.clone()
}

#[tauri::command]
fn ai_credential_status(
    _sidecar: State<'_, ApiSidecar>,
    profile_id: String,
) -> Result<CredentialStatus, String> {
    credential_status(&SystemCredentialStore, &profile_id)
}

#[tauri::command]
fn store_ai_credential(
    sidecar: State<'_, ApiSidecar>,
    profile_id: String,
    api_key: String,
) -> Result<CredentialStatus, String> {
    store_and_activate(
        &SystemCredentialStore,
        &sidecar.connection,
        &profile_id,
        api_key,
    )
}

#[tauri::command]
fn activate_ai_credential(
    sidecar: State<'_, ApiSidecar>,
    profile_id: String,
) -> Result<CredentialStatus, String> {
    activate_saved(&SystemCredentialStore, &sidecar.connection, &profile_id)
}

#[tauri::command]
fn delete_ai_credential(
    sidecar: State<'_, ApiSidecar>,
    profile_id: String,
) -> Result<CredentialStatus, String> {
    delete_credential(&SystemCredentialStore, &sidecar.connection, &profile_id)
}

fn generate_session_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "无法生成本地 API 会话令牌".to_owned())?;
    Ok(hex::encode(bytes))
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
        if let Ok(mut stream) = TcpStream::connect_timeout(&address.into(), HEALTH_REQUEST_TIMEOUT)
        {
            let _ = stream.set_read_timeout(Some(HEALTH_REQUEST_TIMEOUT));
            let _ = stream.set_write_timeout(Some(HEALTH_REQUEST_TIMEOUT));
            if stream
                .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                .is_ok()
            {
                let mut response = Vec::with_capacity(1024);
                let _ = stream.take(4096).read_to_end(&mut response);
                if is_healthy_http_response(&response) {
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
    let session_token = generate_session_token()?;
    let command = app
        .shell()
        .sidecar("mozhou-api")
        .map_err(|error| format!("无法定位本地 API：{error}"))?
        .args(["--port", &port.to_string()])
        .env(SESSION_TOKEN_ENV, &session_token);
    let (mut events, child) = command
        .spawn()
        .map_err(|error| format!("无法启动本地 API：{error}"))?;
    tauri::async_runtime::spawn(async move { while events.recv().await.is_some() {} });

    if !wait_for_health(port, SIDECAR_STARTUP_TIMEOUT) {
        let _ = child.kill();
        return Err("本地 API 未能在限定时间内完成健康检查".to_owned());
    }

    Ok(ApiSidecar {
        connection: ApiConnection {
            base_url: format!("http://127.0.0.1:{port}"),
            session_token,
        },
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
        .invoke_handler(tauri::generate_handler![
            api_connection,
            ai_credential_status,
            store_ai_credential,
            activate_ai_credential,
            delete_ai_credential,
        ])
        .setup(|app| {
            let sidecar = start_api_sidecar(app).map_err(std::io::Error::other)?;
            let _ = restore_active_profile(&SystemCredentialStore, &sidecar.connection);
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
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread::{self, sleep};
    use std::time::Duration;

    use super::{
        generate_session_token, is_healthy_http_response, select_loopback_port, wait_for_health,
    };

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

    #[test]
    fn generates_a_fresh_256_bit_hex_session_token() {
        let first = generate_session_token().expect("token generation should succeed");
        let second = generate_session_token().expect("token generation should succeed");

        assert_eq!(first.len(), 64);
        assert!(first.bytes().all(|byte| byte.is_ascii_hexdigit()));
        assert_eq!(first, first.to_ascii_lowercase());
        assert_ne!(first, second);
    }

    #[test]
    fn waits_for_a_complete_fragmented_health_response() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("listener should bind");
        let port = listener
            .local_addr()
            .expect("listener should have an address")
            .port();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("health request should connect");
            let mut request = [0_u8; 256];
            let _ = stream.read(&mut request);
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: 15\r\nconnection: close\r\n\r\n",
                )
                .expect("headers should write");
            stream.flush().expect("headers should flush");
            sleep(Duration::from_millis(20));
            stream
                .write_all(br#"{"status":"ok"}"#)
                .expect("body should write");
        });

        assert!(wait_for_health(port, Duration::from_secs(1)));
        server.join().expect("health server should exit");
    }
}
