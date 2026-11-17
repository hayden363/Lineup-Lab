import SwiftUI

/// Everything that isn't a main tab: the rest of the fantasy tools, notifications, legal, and the account.
struct MoreView: View {
    @EnvironmentObject private var auth: AuthManager
    @EnvironmentObject private var push: PushManager
    @State private var confirmSignOut = false
    @State private var showDelete = false

    private let tools: [(String, String, String)] = [
        ("NFL Games", "sportscourt", "/?tab=live"),
        ("Waivers", "chart.line.uptrend.xyaxis", "/?tab=waivers"),
        ("Trade", "arrow.triangle.2.circlepath", "/?tab=trade"),
        ("Big Board", "chart.bar", "/?tab=board"),
        ("League Chat", "bubble.left.and.bubble.right", "/?tab=chat"),
        ("Settings", "gearshape", "/?tab=settings"),
    ]

    var body: some View {
        List {
            Section("Fantasy tools") {
                ForEach(tools, id: \.2) { t in
                    NavigationLink { WebTab(path: t.2, title: t.0) } label: { Label(t.0, systemImage: t.1) }
                }
            }
            Section {
                Toggle(isOn: Binding(get: { push.driveReminder && push.authorization == .authorized },
                                     set: { on in Task { await setReminder(on) } })) {
                    Label("Daily Drive reminder", systemImage: "bell.badge")
                }
            } header: {
                Text("Notifications")
            } footer: {
                Text(push.authorization == .denied
                     ? "Notifications are off for Lineup Lab. Turn them on in the Settings app."
                     : "Once a day, only if you haven't played yet.")
            }
            Section("About") {
                NavigationLink { WebTab(path: "/support", title: "Support") } label: { Label("Support", systemImage: "questionmark.circle") }
                NavigationLink { WebTab(path: "/legal/privacy", title: "Privacy Policy") } label: { Label("Privacy Policy", systemImage: "hand.raised") }
                NavigationLink { WebTab(path: "/legal/terms", title: "Terms of Service") } label: { Label("Terms of Service", systemImage: "doc.text") }
            }
            Section {
                if !auth.username.isEmpty {
                    LabeledContent("Signed in as", value: auth.username)
                }
                Button("Sign out") { confirmSignOut = true }
                Button("Delete account", role: .destructive) { showDelete = true }
            } header: {
                Text("Account")
            }
        }
        .navigationTitle("More")
        .task { await push.refreshAuthorization() }
        .confirmationDialog("Sign out of Lineup Lab?", isPresented: $confirmSignOut, titleVisibility: .visible) {
            Button("Sign out", role: .destructive) { Task { await auth.signOut() } }
        }
        .sheet(isPresented: $showDelete) { DeleteAccountView() }
    }

    private func setReminder(_ on: Bool) async {
        if on && push.authorization != .authorized {
            await push.requestPermission()
        }
        push.driveReminder = on
        await push.upload()
    }
}

/// Permanent account deletion (Guideline 5.1.1(v)). Same rules as the website: type DELETE, plus the password when the
/// account has one (Apple and Google accounts don't).
struct DeleteAccountView: View {
    @EnvironmentObject private var auth: AuthManager
    @Environment(\.dismiss) private var dismiss
    @State private var typed = ""
    @State private var password = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("This permanently deletes your Lineup Lab account and everything tied to it: connected leagues, settings, Daily Drive history and notification settings. It can't be undone.")
                }
                if auth.hasPassword {
                    Section("Your password") {
                        SecureField("Password", text: $password).textContentType(.password)
                    }
                }
                Section("Type DELETE to confirm") {
                    TextField("DELETE", text: $typed).textInputAutocapitalization(.characters).autocorrectionDisabled()
                }
                Section {
                    Button("Delete my account", role: .destructive) {
                        Task { if await auth.deleteAccount(password: password) { dismiss() } }
                    }
                    .disabled(typed != "DELETE" || (auth.hasPassword && password.isEmpty) || auth.busy)
                }
            }
            .navigationTitle("Delete account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
    }
}
