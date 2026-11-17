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

    /// Signs out locally: removes every cookie and cached page for our site.
    func clear() async {
        for cookie in await cookieStore.allCookies() {
            await cookieStore.deleteCookie(cookie)
        }
        let types = WKWebsiteDataStore.allWebsiteDataTypes()
        await dataStore.removeData(ofTypes: types, modifiedSince: .distantPast)
    }
}
