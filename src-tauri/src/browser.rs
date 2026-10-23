//! Repère la page ouverte dans le navigateur au premier plan (Chrome, Edge, Brave, Firefox…),
//! pour que la languette propose d'enregistrer l'article. L'adresse est lue dans la barre
//! d'adresse par l'UI Automation de Windows : aucune extension à installer. Rien n'est stocké,
//! et l'adresse ne part que vers la languette, quand elle change.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};

#[derive(Clone, Serialize, PartialEq)]
pub struct Page {
    url: String,
    title: String,
    browser: String,
}

pub struct Watch {
    enabled: AtomicBool,
    page: Mutex<Option<Page>>,
}

impl Default for Watch {
    fn default() -> Self {
        // Coupé tant que le réglage n'est pas lu : la languette ne regarde rien sans accord.
        Self { enabled: AtomicBool::new(false), page: Mutex::new(None) }
    }
}

#[tauri::command]
pub fn current_page(state: State<Watch>) -> Option<Page> {
    state.page.lock().unwrap().clone()
}

/// Le réglage « Repérer l'article ouvert dans le navigateur ».
#[tauri::command]
pub fn set_page_watch(app: AppHandle, state: State<Watch>, enabled: bool) {
    state.enabled.store(enabled, Ordering::Relaxed);
    if !enabled {
        publish(&app, None);
    }
}

fn publish(app: &AppHandle, page: Option<Page>) {
    let watch = app.state::<Watch>();
    let mut current = watch.page.lock().unwrap();
    if *current != page {
        *current = page.clone();
        let _ = app.emit_to("bulle", "browser-page", page.clone());
        // Le tutoriel, dans la fenêtre principale, montre que la languette a repéré l'article.
        let _ = app.emit_to("main", "browser-page", page);
    }
}

pub fn start(app: AppHandle) {
    #[cfg(windows)]
    std::thread::spawn(move || imp::run(app));
    #[cfg(not(windows))]
    let _ = app;
}

/// « https:// » est masqué par Chrome et Edge ; les pages internes (chrome://, about:…) et le
/// texte en cours de frappe ne sont pas des adresses web.
fn web_url(raw: &str) -> Option<String> {
    let raw = raw.trim();
    if raw.is_empty() || raw.contains(char::is_whitespace) {
        return None;
    }
    if raw.starts_with("http://") || raw.starts_with("https://") {
        return Some(raw.to_string());
    }
    let host = raw.split('/').next().unwrap_or("");
    (!raw.contains("://") && !raw.contains(':') && host.contains('.')).then(|| format!("https://{raw}"))
}

/// Retire le nom du navigateur (« … - Google Chrome », « … — Mozilla Firefox », « … – Brave ») :
/// tiret, demi-cadratin ou cadratin selon le navigateur et la langue.
fn page_title(window: &str) -> String {
    let names = ["Google Chrome", "Microsoft", "Mozilla Firefox", "Brave", "Opera", "Vivaldi"];
    let cut = ["-", "–", "—"]
        .iter()
        .flat_map(|dash| names.iter().map(move |name| format!(" {dash} {name}")))
        .filter_map(|m| window.find(&m))
        .min()
        .unwrap_or(window.len());
    window[..cut].trim().to_string()
}

#[cfg(windows)]
mod imp {
    use std::time::Duration;

    use tauri::{AppHandle, Manager};
    use uiautomation::patterns::UIValuePattern;
    use uiautomation::types::{ControlType, Handle, TreeScope, UIProperty};
    use uiautomation::variants::Variant;
    use uiautomation::UIAutomation;
    use windows::core::PWSTR;
    use windows::Win32::Foundation::{CloseHandle, HWND};
    use windows::Win32::System::Threading::{OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION};
    use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowTextW, GetWindowThreadProcessId};

    use super::{page_title, publish, web_url, Page, Watch};
    use std::sync::atomic::Ordering;

    const BROWSERS: &[(&str, &str)] = &[("chrome.exe", "Chrome"), ("msedge.exe", "Edge"), ("brave.exe", "Brave"), ("firefox.exe", "Firefox"), ("opera.exe", "Opera"), ("vivaldi.exe", "Vivaldi")];
    /// Fenêtres de navigation privée : jamais lues.
    const PRIVATE: &[&str] = &["InPrivate", "Incognito", "Navigation privée", "Private Browsing", "Navigation en mode privé"];

    pub fn run(app: AppHandle) {
        let Ok(uia) = UIAutomation::new() else { return };
        let own = std::process::id();
        let mut last: Option<(isize, String)> = None;
        loop {
            std::thread::sleep(Duration::from_millis(800));
            if !app.state::<Watch>().enabled.load(Ordering::Relaxed) {
                last = None;
                continue;
            }
            let hwnd = unsafe { GetForegroundWindow() };
            if hwnd.is_invalid() {
                continue;
            }
            let mut pid = 0u32;
            unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) };
            if pid == own {
                continue; // la languette ou la fenêtre principale : on garde la page en cours
            }
            let Some(browser) = exe_name(pid).and_then(|exe| BROWSERS.iter().find(|(e, _)| exe.eq_ignore_ascii_case(e)).map(|(_, b)| *b)) else {
                last = None;
                publish(&app, None);
                continue;
            };
            // On ne relit la barre d'adresse que lorsque le titre change : chargement, onglet.
            let title = window_text(hwnd);
            let key = (hwnd.0 as isize, title.clone());
            if last.as_ref() == Some(&key) {
                continue;
            }
            last = Some(key);
            let page = if PRIVATE.iter().any(|m| title.contains(m)) {
                None
            } else {
                address_bar(&uia, hwnd).and_then(|v| web_url(&v)).map(|url| Page { url, title: page_title(&title), browser: browser.to_string() })
            };
            publish(&app, page);
        }
    }

    fn exe_name(pid: u32) -> Option<String> {
        unsafe {
            let process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
            let mut buf = [0u16; 1024];
            let mut len = buf.len() as u32;
            let ok = QueryFullProcessImageNameW(process, PROCESS_NAME_WIN32, PWSTR(buf.as_mut_ptr()), &mut len).is_ok();
            let _ = CloseHandle(process);
            ok.then(|| String::from_utf16_lossy(&buf[..len as usize]).rsplit('\\').next().unwrap_or_default().to_string())
        }
    }

    fn window_text(hwnd: HWND) -> String {
        let mut buf = [0u16; 512];
        let len = unsafe { GetWindowTextW(hwnd, &mut buf) };
        String::from_utf16_lossy(&buf[..len.max(0) as usize])
    }

    /// Le premier champ de saisie de la fenêtre est la barre d'adresse (celle de Firefox porte
    /// l'identifiant « urlbar-input ») : la barre d'outils précède le contenu dans l'arbre.
    fn address_bar(uia: &UIAutomation, hwnd: HWND) -> Option<String> {
        let window = uia.element_from_handle(Handle::from(hwnd)).ok()?;
        let by_id = uia.create_property_condition(UIProperty::AutomationId, Variant::from("urlbar-input"), None).ok()?;
        let edit = uia.create_property_condition(UIProperty::ControlType, Variant::from(ControlType::Edit as i32), None).ok()?;
        let field = window.find_first(TreeScope::Descendants, &by_id).or_else(|_| window.find_first(TreeScope::Descendants, &edit)).ok()?;
        field.get_pattern::<UIValuePattern>().ok()?.get_value().ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urls_from_the_address_bar() {
        assert_eq!(web_url("lemonde.fr/politique/article/x").as_deref(), Some("https://lemonde.fr/politique/article/x"));
        assert_eq!(web_url("https://www.bbc.com/news/1").as_deref(), Some("https://www.bbc.com/news/1"));
        assert_eq!(web_url("chrome://settings"), None);
        assert_eq!(web_url("about:blank"), None);
        assert_eq!(web_url("budget assemblée"), None);
        assert_eq!(web_url("localhost:1427"), None);
    }

    #[test]
    fn titles_without_browser_name() {
        assert_eq!(page_title("Le budget est voté - Google Chrome"), "Le budget est voté");
        assert_eq!(page_title("Le budget est voté — Mozilla Firefox"), "Le budget est voté");
        assert_eq!(page_title("Le budget - Personnel - Microsoft\u{200b} Edge"), "Le budget - Personnel");
        assert_eq!(page_title("Les juges sous pression – Brave"), "Les juges sous pression");
    }
}
