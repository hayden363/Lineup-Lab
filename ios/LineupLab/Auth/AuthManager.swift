import AuthenticationServices
import CryptoKit
import SwiftUI

/// Who is signed in, and every way in or out:
///   Sign in with Apple  -> POST /api/auth/apple (identity token + nonce)
///   Google              -> system sign-in sheet -> lineuplab://auth?code= -> POST /api/auth/app-exchange
///   Email               -> the site's own sign-in form, shown in a sheet
/// The session is the server's cookie in the shared web view cookie store (WebSession).
@MainActor
final class AuthManager: NSObject, ObservableObject {
    static let shared = AuthManager()

    enum Status { case unknown, signedOut, signedIn }

    @Published var status: Status = .unknown
    @Published var user: [String: Any] = [:]
    @Published var error: String?
    @Published var busy = false
    /// Bumped on every sign-in or out so every tab reloads with the new session.
    @Published var sessionGeneration = 0

    private var appleNonce: String?
    private var appleContinuation: CheckedContinuation<Bool, Never>?
    private var webAuth: ASWebAuthenticationSession?

    var hasPassword: Bool { user["has_password"] as? Bool ?? false }
    var username: String { user["username"] as? String ?? "" }

    /// Checks the saved session with the server (GET /api/auth/me).
    func refresh() async {
        guard await WebSession.shared.isSignedIn else { status = .signedOut; return }
        do {
            user = try await API.get("/api/auth/me")
            status = .signedIn
        } catch {
            status = .signedOut
        }
    }

    func markSignedOut() {
        if status == .signedIn { status = .signedOut }
    }

    private func didSignIn() async {
        await refresh()
        if status == .signedIn {
            sessionGeneration += 1
            await PushManager.shared.registerIfAllowed()
        }
    }

    // MARK: Sign in with Apple

    func appleRequest(_ request: ASAuthorizationAppleIDRequest) {
        let nonce = Self.randomNonce()
        appleNonce = nonce
        request.requestedScopes = [.fullName, .email]
        request.nonce = Self.sha256(nonce)
    }

    func appleCompletion(_ result: Result<ASAuthorization, Error>) {
        Task { await handleApple(result) }
    }

    private func handleApple(_ result: Result<ASAuthorization, Error>) async {
        switch result {
        case .failure(let err):
            if (err as? ASAuthorizationError)?.code != .canceled { error = "Sign in with Apple didn't finish. Please try again." }
        case .success(let auth):
            guard let cred = auth.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = cred.identityToken, let token = String(data: tokenData, encoding: .utf8),
                  let nonce = appleNonce else {
                error = "Sign in with Apple didn't return a token."
                return
            }
            var body: [String: Any] = ["identity_token": token, "nonce": nonce]
            if let name = cred.fullName {
                let full = PersonNameComponentsFormatter().string(from: name).trimmingCharacters(in: .whitespaces)
                if !full.isEmpty { body["full_name"] = full }
            }
            busy = true
            defer { busy = false }
            do {
                try await API.post("/api/auth/apple", body)
                await didSignIn()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    // MARK: Google (system sign-in sheet)

    @discardableResult
    func signInWithGoogle() async -> Bool {
        let start = Config.url("/api/auth/google/start?app=1")
        let callback: URL? = await withCheckedContinuation { cont in
            let session = ASWebAuthenticationSession(url: start, callbackURLScheme: Config.callbackScheme) { url, _ in
                cont.resume(returning: url)
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = false
            webAuth = session
            if !session.start() { cont.resume(returning: nil) }
        }
        webAuth = nil
        guard let url = callback,
              let code = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "code" })?.value
        else {
            if callback != nil { error = "Google sign-in didn't finish. Please try again." }
            return false
        }
        busy = true
        defer { busy = false }
        do {
            try await API.post("/api/auth/app-exchange", ["code": code])
            await didSignIn()
            return status == .signedIn
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    // MARK: Email: the site's own form finished signing in (the sheet calls this)

    func emailSignInFinished() async {
        await didSignIn()
    }

    // MARK: Out

    func signOut() async {
        await PushManager.shared.unregister()
        _ = try? await API.post("/api/auth/logout", [:])
        await WebSession.shared.clear()
        user = [:]
        status = .signedOut
        sessionGeneration += 1
    }

    /// Permanently deletes the account (POST /api/auth/delete-account; Guideline 5.1.1(v)).
    func deleteAccount(password: String) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            await PushManager.shared.unregister()
            try await API.post("/api/auth/delete-account", ["password": password, "confirm": "DELETE"])
            await WebSession.shared.clear()
            user = [:]
            status = .signedOut
            sessionGeneration += 1
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    // MARK: helpers

    private static func randomNonce(length: Int = 32) -> String {
        let chars = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")
        var out = ""
        var rng = SystemRandomNumberGenerator()
        for _ in 0..<length { out.append(chars[Int(rng.next(upperBound: UInt32(chars.count)))]) }
        return out
    }

    private static func sha256(_ s: String) -> String {
        SHA256.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

extension AuthManager: ASWebAuthenticationPresentationContextProviding {
    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            let scene = UIApplication.shared.connectedScenes.first { $0.activationState == .foregroundActive } as? UIWindowScene
            return scene?.windows.first { $0.isKeyWindow } ?? ASPresentationAnchor()
        }
    }
}
