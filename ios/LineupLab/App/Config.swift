import Foundation

/// Where the app's web content lives, and the few constants native code shares with the server.
enum Config {
    /// The live Lineup Lab site. Every tab is a page of it.
    static let baseURL = URL(string: "https://lineup-lab-awdv.onrender.com")!

    /// The server's session cookie (server.py SESSION_COOKIE).
    static let sessionCookie = "eb_session"

    /// Our URL scheme: Google sign-in returns here with a one-time code (server.py _issue_app_code).
    static let callbackScheme = "lineuplab"

    /// Added to every web view's user agent so the site switches to in-app mode (static/theme-boot.js).
    static var userAgentSuffix: String {
        let v = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
        return "LineupLabApp/\(v)"
    }

    static func url(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }
}
