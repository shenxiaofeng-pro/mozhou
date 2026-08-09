use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::time::Duration;

use keyring::v1::{Entry, Error as KeyringError};
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use zeroize::Zeroize;

use crate::ApiConnection;

const CREDENTIAL_SERVICE: &str = "com.lingjing.mozhou.ai";
const ACTIVE_PROFILE_ACCOUNT: &str = "active-profile";
const API_REQUEST_TIMEOUT: Duration = Duration::from_secs(5);

pub(crate) trait CredentialStore {
    fn set(&self, account: &str, secret: &str) -> Result<(), String>;
    fn get(&self, account: &str) -> Result<Option<String>, String>;
    fn delete(&self, account: &str) -> Result<(), String>;
}

pub(crate) struct SystemCredentialStore;

impl CredentialStore for SystemCredentialStore {
    fn set(&self, account: &str, secret: &str) -> Result<(), String> {
        credential_entry(account)?
            .set_password(secret)
            .map_err(|_| credential_error())
    }

    fn get(&self, account: &str) -> Result<Option<String>, String> {
        match credential_entry(account)?.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(KeyringError::NoEntry) => Ok(None),
            Err(_) => Err(credential_error()),
        }
    }

    fn delete(&self, account: &str) -> Result<(), String> {
        match credential_entry(account)?.delete_credential() {
            Ok(()) | Err(KeyringError::NoEntry) => Ok(()),
            Err(_) => Err(credential_error()),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CredentialStatus {
    profile_id: String,
    stored: bool,
    active: bool,
}

pub(crate) fn validate_profile_id(profile_id: &str) -> Result<(), String> {
    let valid = profile_id.len() == 36
        && profile_id.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()
            }
        });
    if valid {
        Ok(())
    } else {
        Err("模型配置标识无效".to_owned())
    }
}

pub(crate) fn credential_status(
    store: &impl CredentialStore,
    profile_id: &str,
) -> Result<CredentialStatus, String> {
    validate_profile_id(profile_id)?;
    let account = profile_account(profile_id);
    let mut secret = store.get(&account)?;
    let stored = secret.is_some();
    if let Some(value) = secret.as_mut() {
        value.zeroize();
    }
    let mut active_profile = store.get(ACTIVE_PROFILE_ACCOUNT)?;
    let active = active_profile.as_deref() == Some(profile_id);
    if let Some(value) = active_profile.as_mut() {
        value.zeroize();
    }
    Ok(CredentialStatus {
        profile_id: profile_id.to_owned(),
        stored,
        active,
    })
}

pub(crate) fn store_and_activate(
    store: &impl CredentialStore,
    connection: &ApiConnection,
    profile_id: &str,
    mut api_key: String,
) -> Result<CredentialStatus, String> {
    validate_profile_id(profile_id)?;
    if api_key.is_empty() || api_key.len() > 2_000 || api_key.contains('\0') {
        api_key.zeroize();
        return Err("API Key 格式无效".to_owned());
    }
    let account = profile_account(profile_id);
    let result = (|| {
        store.set(&account, &api_key)?;
        activate_runtime_profile(connection, profile_id, &api_key, true)?;
        store.set(ACTIVE_PROFILE_ACCOUNT, profile_id)?;
        credential_status(store, profile_id)
    })();
    api_key.zeroize();
    result
}

pub(crate) fn activate_saved(
    store: &impl CredentialStore,
    connection: &ApiConnection,
    profile_id: &str,
) -> Result<CredentialStatus, String> {
    validate_profile_id(profile_id)?;
    let account = profile_account(profile_id);
    let mut api_key = store
        .get(&account)?
        .ok_or_else(|| "该模型配置尚未保存密钥".to_owned())?;
    let result = (|| {
        activate_runtime_profile(connection, profile_id, &api_key, true)?;
        store.set(ACTIVE_PROFILE_ACCOUNT, profile_id)?;
        credential_status(store, profile_id)
    })();
    api_key.zeroize();
    result
}

pub(crate) fn delete_credential(
    store: &impl CredentialStore,
    connection: &ApiConnection,
    profile_id: &str,
) -> Result<CredentialStatus, String> {
    validate_profile_id(profile_id)?;
    let is_active = store.get(ACTIVE_PROFILE_ACCOUNT)?.as_deref() == Some(profile_id);
    post_api_json(
        connection,
        &format!("/api/ai/profiles/{profile_id}/deactivate"),
        "{}",
    )?;
    if is_active {
        store.delete(ACTIVE_PROFILE_ACCOUNT)?;
    }
    store.delete(&profile_account(profile_id))?;
    credential_status(store, profile_id)
}

#[derive(Deserialize)]
struct RuntimeProfile {
    id: String,
}

pub(crate) fn restore_saved_profiles(
    store: &impl CredentialStore,
    connection: &ApiConnection,
) -> Result<(), String> {
    let active_profile = store.get(ACTIVE_PROFILE_ACCOUNT)?;
    let profiles: Vec<RuntimeProfile> = get_api_json(connection, "/api/ai/profiles")?;
    let mut first_error: Option<String> = None;

    for profile in profiles
        .iter()
        .filter(|profile| active_profile.as_deref() != Some(profile.id.as_str()))
    {
        let mut api_key = store.get(&profile_account(&profile.id))?;
        if let Some(api_key) = api_key.as_mut()
            && let Err(error) = activate_runtime_profile(connection, &profile.id, api_key, false)
        {
            first_error.get_or_insert(error);
        }
        if let Some(api_key) = api_key.as_mut() {
            api_key.zeroize();
        }
    }

    if let Some(profile_id) = active_profile.as_deref()
        && profiles.iter().any(|profile| profile.id == profile_id)
    {
        let mut api_key = store.get(&profile_account(profile_id))?;
        if let Some(api_key) = api_key.as_mut()
            && let Err(error) = activate_runtime_profile(connection, profile_id, api_key, true)
        {
            first_error.get_or_insert(error);
        }
        if let Some(api_key) = api_key.as_mut() {
            api_key.zeroize();
        }
    }

    match first_error {
        Some(error) => Err(error),
        None => Ok(()),
    }
}

pub(crate) fn start_job_runtime(connection: &ApiConnection) -> Result<(), String> {
    post_api_json(connection, "/api/runtime/start", "{}")
}

fn activate_runtime_profile(
    connection: &ApiConnection,
    profile_id: &str,
    api_key: &str,
    make_active: bool,
) -> Result<(), String> {
    let path = format!("/api/ai/profiles/{profile_id}/activate");
    let mut body = serde_json::json!({
        "api_key": api_key,
        "make_active": make_active,
    })
    .to_string();
    let result = post_api_json(connection, &path, &body);
    body.zeroize();
    result
}

fn get_api_json<T: DeserializeOwned>(connection: &ApiConnection, path: &str) -> Result<T, String> {
    let port = api_port(connection)?;
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    let mut stream = TcpStream::connect_timeout(&address.into(), API_REQUEST_TIMEOUT)
        .map_err(|_| "无法连接本地 API".to_owned())?;
    let _ = stream.set_read_timeout(Some(API_REQUEST_TIMEOUT));
    let _ = stream.set_write_timeout(Some(API_REQUEST_TIMEOUT));
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Mozhou-Session-Token: {}\r\nConnection: close\r\n\r\n",
        connection.session_token,
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|_| "本地 API 请求发送失败".to_owned())?;
    let response = read_api_response(stream)?;
    serde_json::from_slice(response_body(&response)?)
        .map_err(|_| "本地 API 响应格式无效".to_owned())
}

fn post_api_json(connection: &ApiConnection, path: &str, body: &str) -> Result<(), String> {
    let port = api_port(connection)?;
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    let mut stream = TcpStream::connect_timeout(&address.into(), API_REQUEST_TIMEOUT)
        .map_err(|_| "无法连接本地 API".to_owned())?;
    let _ = stream.set_read_timeout(Some(API_REQUEST_TIMEOUT));
    let _ = stream.set_write_timeout(Some(API_REQUEST_TIMEOUT));
    let mut request = format!(
        "POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nX-Mozhou-Session-Token: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        connection.session_token,
        body.len(),
    );
    let write_result = stream.write_all(request.as_bytes());
    request.zeroize();
    write_result.map_err(|_| "本地 API 请求发送失败".to_owned())?;
    let response = read_api_response(stream)?;
    if response.starts_with(b"HTTP/1.1 200") {
        Ok(())
    } else {
        Err("本地模型配置未能激活".to_owned())
    }
}

fn api_port(connection: &ApiConnection) -> Result<u16, String> {
    connection
        .base_url
        .strip_prefix("http://127.0.0.1:")
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| "本地 API 地址无效".to_owned())
}

fn read_api_response(stream: TcpStream) -> Result<Vec<u8>, String> {
    let mut response = Vec::with_capacity(1024);
    stream
        .take(65_536)
        .read_to_end(&mut response)
        .map_err(|_| "本地 API 响应读取失败".to_owned())?;
    Ok(response)
}

fn response_body(response: &[u8]) -> Result<&[u8], String> {
    if !response.starts_with(b"HTTP/1.1 200") {
        return Err("本地 API 请求失败".to_owned());
    }
    response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|position| &response[position + 4..])
        .ok_or_else(|| "本地 API 响应格式无效".to_owned())
}

fn credential_entry(account: &str) -> Result<Entry, String> {
    Entry::new(CREDENTIAL_SERVICE, account).map_err(|_| credential_error())
}

fn credential_error() -> String {
    "系统凭据库不可用，可改用仅当前会话的密钥".to_owned()
}

fn profile_account(profile_id: &str) -> String {
    format!("profile:{profile_id}")
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::Mutex;
    use std::thread;

    use super::{
        ACTIVE_PROFILE_ACCOUNT, CredentialStore, SystemCredentialStore, credential_status,
        profile_account, restore_saved_profiles, validate_profile_id,
    };
    use crate::ApiConnection;

    const PROFILE_ID: &str = "4b910e79-9106-4eb1-9cc4-15631314dd45";
    const SECONDARY_PROFILE_ID: &str = "ceef92ea-0115-43d0-a91b-2617f71a82bd";

    #[derive(Default)]
    struct MemoryCredentialStore {
        values: Mutex<HashMap<String, String>>,
    }

    impl CredentialStore for MemoryCredentialStore {
        fn set(&self, account: &str, secret: &str) -> Result<(), String> {
            self.values
                .lock()
                .expect("memory store should lock")
                .insert(account.to_owned(), secret.to_owned());
            Ok(())
        }

        fn get(&self, account: &str) -> Result<Option<String>, String> {
            Ok(self
                .values
                .lock()
                .expect("memory store should lock")
                .get(account)
                .cloned())
        }

        fn delete(&self, account: &str) -> Result<(), String> {
            self.values
                .lock()
                .expect("memory store should lock")
                .remove(account);
            Ok(())
        }
    }

    #[test]
    fn validates_uuid_profile_ids_before_keychain_access() {
        assert!(validate_profile_id(PROFILE_ID).is_ok());
        assert!(validate_profile_id("../active-profile").is_err());
        assert!(validate_profile_id("4B910E79-9106-4EB1-9CC4-15631314DD45").is_err());
    }

    #[test]
    fn reports_only_presence_and_active_state() {
        let store = MemoryCredentialStore::default();
        store
            .set(&profile_account(PROFILE_ID), "never-return-this-secret")
            .expect("secret should save");
        store
            .set(ACTIVE_PROFILE_ACCOUNT, PROFILE_ID)
            .expect("active profile should save");

        let status = credential_status(&store, PROFILE_ID).expect("status should load");

        assert!(status.stored);
        assert!(status.active);
        assert_eq!(status.profile_id, PROFILE_ID);
        store
            .delete(&profile_account(PROFILE_ID))
            .expect("secret should delete");
        assert!(
            !credential_status(&store, PROFILE_ID)
                .expect("status should load")
                .stored
        );
    }

    #[test]
    fn restores_all_saved_profiles_and_makes_the_selected_one_active_last() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("listener should bind");
        let port = listener.local_addr().expect("listener should bind").port();
        let server = thread::spawn(move || {
            let mut requests = Vec::new();
            for index in 0..3 {
                let (mut stream, _) = listener.accept().expect("request should connect");
                let mut request = [0_u8; 4096];
                let size = stream.read(&mut request).expect("request should read");
                requests.push(String::from_utf8_lossy(&request[..size]).into_owned());
                let body = if index == 0 {
                    format!(r#"[{{"id":"{PROFILE_ID}"}},{{"id":"{SECONDARY_PROFILE_ID}"}}]"#,)
                } else {
                    "{}".to_owned()
                };
                write!(
                    stream,
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body,
                )
                .expect("response should write");
            }
            requests
        });
        let store = MemoryCredentialStore::default();
        store
            .set(ACTIVE_PROFILE_ACCOUNT, PROFILE_ID)
            .expect("active profile should save");
        store
            .set(&profile_account(PROFILE_ID), "active-test-key")
            .expect("active key should save");
        store
            .set(&profile_account(SECONDARY_PROFILE_ID), "secondary-test-key")
            .expect("secondary key should save");
        let connection = ApiConnection {
            base_url: format!("http://127.0.0.1:{port}"),
            session_token: "a".repeat(64),
        };

        restore_saved_profiles(&store, &connection).expect("profiles should restore");
        let requests = server.join().expect("server should exit");

        assert!(requests[0].starts_with("GET /api/ai/profiles "));
        assert!(requests[1].contains(&format!(
            "POST /api/ai/profiles/{SECONDARY_PROFILE_ID}/activate "
        )));
        assert!(requests[1].contains(r#""make_active":false"#));
        assert!(requests[2].contains(&format!("POST /api/ai/profiles/{PROFILE_ID}/activate ")));
        assert!(requests[2].contains(r#""make_active":true"#));
    }

    #[test]
    #[ignore = "writes one disposable item to the operating-system credential store"]
    fn system_keychain_round_trip() {
        let store = SystemCredentialStore;
        let account = profile_account("ab11ca85-b810-455e-b597-e49e81480f34");
        let _ = store.delete(&account);

        let result = (|| {
            store.set(&account, "mozhou-disposable-keychain-check")?;
            store.get(&account)
        })();
        let cleanup = store.delete(&account);

        assert_eq!(
            result
                .expect("system credential should round-trip")
                .as_deref(),
            Some("mozhou-disposable-keychain-check")
        );
        cleanup.expect("disposable system credential should be removed");
        assert_eq!(
            store
                .get(&account)
                .expect("deleted credential should be queryable"),
            None
        );
    }
}
