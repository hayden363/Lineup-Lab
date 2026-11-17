import AuthenticationServices
import SwiftUI

/// The signed-out front door: Lineup Lab first, the Daily Drive as the way in, then the ways to sign in.
struct WelcomeView: View {
    var onPlayAsGuest: () -> Void
    @EnvironmentObject private var auth: AuthManager
    @State private var emailMode: EmailSheet.Mode?

    var body: some View {
        ZStack {
            Color("LaunchBackground").ignoresSafeArea()
            ScrollView {
                VStack(spacing: 22) {
                    HStack(spacing: 12) {
                        Image("LaunchLogo").resizable().scaledToFit().frame(width: 44, height: 44)
                            .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                        Text("Lineup Lab").font(.title2.bold())
                    }
                    .padding(.top, 24)

                    VStack(spacing: 6) {
                        Text("Play football every day.").font(.system(size: 30, weight: .heavy))
                        Text("Win your league on Sunday.").font(.system(size: 30, weight: .heavy)).foregroundStyle(Color("AccentColor"))
                    }
                    .multilineTextAlignment(.center)

                    Button(action: onPlayAsGuest) {
                        VStack(alignment: .leading, spacing: 10) {
                            Image("DriveCover").resizable().scaledToFill().frame(height: 170).clipped()
                                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                            Text("The Daily Drive").font(.title3.bold())
                            Text("Seven NFL trivia plays a day, free. The rarer your answer, the bigger the play.")
                                .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.leading)
                            Label("Play today's drive", systemImage: "play.fill").font(.headline).foregroundStyle(Color("AccentColor"))
                        }
                        .padding(14)
                        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Color.white.opacity(0.06)))
                        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color("AccentColor").opacity(0.45)))
                    }
                    .buttonStyle(.plain)

                    VStack(spacing: 12) {
                        Text("Sign in for your fantasy tools: Start/Sit, waivers, trades and live scores for your Sleeper or ESPN league.")
                            .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        SignInWithAppleButton(.signIn, onRequest: auth.appleRequest, onCompletion: auth.appleCompletion)
                            .signInWithAppleButtonStyle(.white)
                            .frame(height: 50)
                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        Button {
                            Task { await auth.signInWithGoogle() }
                        } label: {
                            Label("Continue with Google", systemImage: "g.circle.fill")
                                .font(.headline).frame(maxWidth: .infinity, minHeight: 50)
                        }
                        .buttonStyle(.bordered).tint(.white)
                        HStack {
                            Button("Sign in with email") { emailMode = .login }
                            Text("·").foregroundStyle(.secondary)
                            Button("Create an account") { emailMode = .signup }
                        }
                        .font(.subheadline)
                    }
                    .disabled(auth.busy)

                    HStack(spacing: 14) {
                        Link("Privacy", destination: Config.url("/legal/privacy"))
                        Link("Terms", destination: Config.url("/legal/terms"))
                        Link("Support", destination: Config.url("/support"))
                    }
                    .font(.caption).foregroundStyle(.secondary)
                    .padding(.bottom, 24)
                }
                .padding(.horizontal, 22)
                .frame(maxWidth: 520)
                .frame(maxWidth: .infinity)
            }
            if auth.busy { ProgressView().controlSize(.large).tint(.white) }
        }
        .sheet(item: $emailMode) { mode in EmailSheet(mode: mode) }
    }
}

/// The site's own email sign-in / sign-up form in a sheet. It signs in with a fetch, not a page load, so the sheet
/// watches the shared cookie store and closes as soon as the session cookie appears.
struct EmailSheet: View {
    enum Mode: String, Identifiable { case login, signup; var id: String { rawValue } }
    let mode: Mode
    @EnvironmentObject private var auth: AuthManager
    @Environment(\.dismiss) private var dismiss
    @State private var state: WebLoadState = .loading

    var body: some View {
        NavigationStack {
            WebView(url: Config.url("/?auth=\(mode.rawValue)"), state: $state)
                .ignoresSafeArea(edges: .bottom)
                .navigationTitle(mode == .login ? "Sign in" : "Create account")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 800_000_000)
                if await WebSession.shared.isSignedIn {
                    await auth.emailSignInFinished()
                    dismiss()
                    return
                }
            }
        }
    }
}
