import Foundation
import WebKit

/// One cookie jar for every tab: signing in once signs in everywhere. Native API calls (Sign in with Apple, push
/// registration, account deletion) read and write the same cookies, so the web views and native code stay in step.
@MainActor
final class WebSession {
    static let shared = WebSession()

    let dataStore = WKWebsiteDataStore.default()

    private var cookieStore: WKHTTPCookieStore { dataStore.httpCookieStore }

    /// A configuration every tab's WKWebView is built from (shared data store, the in-app bridge).
    func makeConfiguration(bridge: WKScriptMessageHandler) -> WKWebViewConfiguration {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = dataStore
        config.applicationNameForUserAgent = Config.userAgentSuffix
        config.allowsInlineMediaPlayback = true
        let ucc = WKUserContentController()
        for name in NativeBridge.handlerNames {
            ucc.add(bridge, name: name)
        }
        config.userContentController = ucc
        return config
    }

    /// Copies the session cookie(s) a native request received into the web views' cookie store.
    func adopt(cookiesFrom response: HTTPURLResponse) async {
        guard let url = response.url,
              let headers = response.allHeaderFields as? [String: String] else { return }
        for cookie in HTTPCookie.cookies(withResponseHeaderFields: headers, for: url) {
            await cookieStore.setCookie(cookie)
        }
    }

    /// The "Cookie" header value for a native request to our server.
    func cookieHeader() async -> String? {
        let host = Config.baseURL.host ?? ""
        let cookies = await cookieStore.allCookies().filter { host.hasSuffix($0.domain.trimmingCharacters(in: CharacterSet(charactersIn: "."))) }
        guard !cookies.isEmpty else { return nil }
        return cookies.map { "\($0.name)=\($0.value)" }.joined(separator: "; ")
    }

    var isSignedIn: Bool {
        get async {
            let cookies = await cookieStore.allCookies()
            return cookies.contains { $0.name == Config.sessionCookie && !$0.value.isEmpty }
        }
    }

    private func sessionCookie() async -> HTTPCookie? {
        await cookieStore.allCookies().first { $0.name == Config.sessionCookie && !$0.value.isEmpty }
    }

    /// Keeps a Keychain copy of the current sign-in.
    func rememberSession() async {
        if let cookie = await sessionCookie() { SessionVault.save(cookie.value) }
    }

    /// If the cookie store lost the sign-in, puts it back from the Keychain before anything checks or loads a page.
    func restoreSession() async {
        SessionVault.clearIfFreshInstall()
        guard await sessionCookie() == nil, let token = SessionVault.load(), let host = Config.baseURL.host else { return }
        var properties: [HTTPCookiePropertyKey: Any] = [
            .name: Config.sessionCookie, .value: token, .domain: host, .path: "/",
            .expires: Date().addingTimeInterval(30 * 24 * 60 * 60),     // the server decides when the session really ends
            .sameSitePolicy: HTTPCookieStringPolicy.sameSiteLax, HTTPCookiePropertyKey("HttpOnly"): "TRUE",
        ]
        if Config.baseURL.scheme == "https" { properties[.secure] = "TRUE" }
        if let cookie = HTTPCookie(properties: properties) { await cookieStore.setCookie(cookie) }
    }

    /// The server said this sign-in is over: removes both copies, so the next launch shows the welcome screen.
    func forgetSession() async {
        SessionVault.clear()
        if let cookie = await sessionCookie() { await cookieStore.deleteCookie(cookie) }
    }

    /// Signs out locally: removes the saved sign-in and every cookie and cached page for our site.
    func clear() async {
        SessionVault.clear()
        for cookie in await cookieStore.allCookies() {
            await cookieStore.deleteCookie(cookie)
        }
        let types = WKWebsiteDataStore.allWebsiteDataTypes()
        await dataStore.removeData(ofTypes: types, modifiedSince: .distantPast)
    }
}
