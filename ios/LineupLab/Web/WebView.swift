import SafariServices
import SwiftUI
import WebKit

/// Load state a tab shows on top of its web view.
enum WebLoadState: Equatable {
    case loading, ready, offline(String)
}

/// One page of the Lineup Lab site in a WKWebView that shares the app's cookies.
/// - Pages on our site stay in the web view; any other site opens in Safari View Controller.
/// - The web sign-in form's "Continue with Google" link is caught and run in the system sign-in sheet instead
///   (Google refuses sign-in inside embedded web views), then the page reloads signed in.
struct WebView: UIViewRepresentable {
    let url: URL
    @Binding var state: WebLoadState
    var reloadToken: Int = 0
    var onSignedOut: (() -> Void)? = nil

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let web = WKWebView(frame: .zero, configuration: WebSession.shared.makeConfiguration(bridge: context.coordinator.bridge))
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = true
        web.isOpaque = false
        web.backgroundColor = UIColor(named: "LaunchBackground")
        web.scrollView.backgroundColor = UIColor(named: "LaunchBackground")
        web.scrollView.contentInsetAdjustmentBehavior = .automatic
        let refresh = UIRefreshControl()
        refresh.tintColor = .white
        refresh.addTarget(context.coordinator, action: #selector(Coordinator.pulled(_:)), for: .valueChanged)
        web.scrollView.refreshControl = refresh
        context.coordinator.webView = web
        web.load(URLRequest(url: url))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        context.coordinator.parent = self
        if context.coordinator.lastReload != reloadToken {
            context.coordinator.lastReload = reloadToken
            if web.url == nil { web.load(URLRequest(url: url)) } else { web.reload() }
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var parent: WebView
        weak var webView: WKWebView?
        let bridge = NativeBridge()
        var lastReload = 0

        init(_ parent: WebView) {
            self.parent = parent
            self.lastReload = parent.reloadToken
        }

        @objc func pulled(_ sender: UIRefreshControl) {
            webView?.reload()
        }

        private func isOurs(_ url: URL) -> Bool {
            url.host == Config.baseURL.host
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            if url.scheme == "mailto" || url.scheme == "tel" || url.scheme == "sms" {
                UIApplication.shared.open(url)
                return decisionHandler(.cancel)
            }
            if isOurs(url) && url.path == "/api/auth/google/start" {
                decisionHandler(.cancel)
                Task { @MainActor in
                    if await AuthManager.shared.signInWithGoogle() { webView.load(URLRequest(url: self.parent.url)) }
                }
                return
            }
            if isOurs(url) && url.path == "/welcome" {
                // the site's signed-out front door: inside the app the native welcome screen is the front door
                decisionHandler(.cancel)
                Task { @MainActor in self.parent.onSignedOut?() }
                return
            }
            if !isOurs(url) && (url.scheme == "https" || url.scheme == "http") && action.navigationType == .linkActivated {
                decisionHandler(.cancel)
                Task { @MainActor in
                    NativeBridge.topViewController()?.present(SFSafariViewController(url: url), animated: true)
                }
                return
            }
            decisionHandler(.allow)
        }

        // target="_blank" links: open our pages in place, others in Safari View Controller
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = action.request.url {
                if isOurs(url) { webView.load(URLRequest(url: url)) }
                else { NativeBridge.topViewController()?.present(SFSafariViewController(url: url), animated: true) }
            }
            return nil
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            if case .offline = parent.state { parent.state = .loading }
            if webView.url == nil || parent.state != .ready { parent.state = .loading }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.state = .ready
            webView.scrollView.refreshControl?.endRefreshing()
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            failed(error)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            failed(error)
        }

        private func failed(_ error: Error) {
            webView?.scrollView.refreshControl?.endRefreshing()
            let ns = error as NSError
            if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
            parent.state = .offline(ns.localizedDescription)
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }
    }
}
