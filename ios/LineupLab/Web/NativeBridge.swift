import UIKit
import WebKit

/// Messages the web pages send to the app (static/play.js `nativeCall`):
///   share  - text to share (the Daily Drive result)  -> the iOS share sheet
///   haptic - "success" | "light" | "error"           -> a haptic tap as a play lands
final class NativeBridge: NSObject, WKScriptMessageHandler {
    static let handlerNames = ["share", "haptic"]

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        switch message.name {
        case "share":
            guard let text = message.body as? String, !text.isEmpty else { return }
            Task { @MainActor in Self.presentShare(text, from: message.webView) }
        case "haptic":
            let kind = message.body as? String ?? "light"
            Task { @MainActor in Self.haptic(kind) }
        default:
            break
        }
    }

    @MainActor
    static func haptic(_ kind: String) {
        switch kind {
        case "success": UINotificationFeedbackGenerator().notificationOccurred(.success)
        case "error": UINotificationFeedbackGenerator().notificationOccurred(.error)
        default: UIImpactFeedbackGenerator(style: .light).impactOccurred()
        }
    }

    @MainActor
    static func presentShare(_ text: String, from view: UIView?) {
        let vc = UIActivityViewController(activityItems: [text], applicationActivities: nil)
        guard let presenter = topViewController() else { return }
        if let pop = vc.popoverPresentationController {          // iPad: anchor the popover
            let anchor = view ?? presenter.view!
            pop.sourceView = anchor
            pop.sourceRect = CGRect(x: anchor.bounds.midX, y: anchor.bounds.maxY - 120, width: 1, height: 1)
        }
        presenter.present(vc, animated: true)
    }

    @MainActor
    static func topViewController() -> UIViewController? {
        let scene = UIApplication.shared.connectedScenes.first { $0.activationState == .foregroundActive } as? UIWindowScene
        var top = scene?.windows.first { $0.isKeyWindow }?.rootViewController
        while let next = top?.presentedViewController { top = next }
        return top
    }
}
