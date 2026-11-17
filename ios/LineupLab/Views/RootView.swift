import SwiftUI

/// The app's tabs. iPhone: a bottom tab bar. iPad (iOS 18+): the same tabs as a sidebar.
enum AppTab: String, CaseIterable, Identifiable {
    case drive, myteam, startsit, news, more
    var id: String { rawValue }

    var title: String {
        switch self {
        case .drive: return "Daily Drive"
        case .myteam: return "My Team"
        case .startsit: return "Start/Sit"
        case .news: return "News"
        case .more: return "More"
        }
    }

    var icon: String {
        switch self {
        case .drive: return "football.fill"
        case .myteam: return "shield.lefthalf.filled"
        case .startsit: return "arrow.left.arrow.right"
        case .news: return "newspaper"
        case .more: return "ellipsis.circle"
        }
    }

    var path: String? {
        switch self {
        case .drive: return "/play"
        case .myteam: return "/?tab=myteam"
        case .startsit: return "/?tab=startsit"
        case .news: return "/?tab=news"
        case .more: return nil
        }
    }

    /// The tab a notification's path belongs to.
    static func forPath(_ path: String) -> AppTab {
        if path.hasPrefix("/play") { return .drive }
        if path.contains("tab=startsit") { return .startsit }
        if path.contains("tab=news") { return .news }
        if path.contains("tab=myteam") { return .myteam }
        return .drive
    }
}

struct RootView: View {
    @EnvironmentObject private var auth: AuthManager
    @EnvironmentObject private var push: PushManager
    @State private var tab: AppTab = .drive
    @State private var guest = false

    var body: some View {
        Group {
            switch auth.status {
            case .unknown:
                SplashView()
            case .signedOut:
                if guest { GuestDriveView(onSignIn: { guest = false }) }
                else { WelcomeView(onPlayAsGuest: { guest = true }) }
            case .signedIn:
                tabs
            }
        }
        .onChange(of: push.openPath) { _, path in
            guard let path else { return }
            tab = AppTab.forPath(path)
            push.openPath = nil
        }
        .onChange(of: auth.status) { _, status in
            if status == .signedIn { guest = false }
        }
        .alert("Lineup Lab", isPresented: Binding(get: { auth.error != nil }, set: { if !$0 { auth.error = nil } })) {
            Button("OK", role: .cancel) { auth.error = nil }
        } message: {
            Text(auth.error ?? "")
        }
    }

    @ViewBuilder private var tabs: some View {
        TabView(selection: $tab) {
            ForEach(AppTab.allCases) { t in
                NavigationStack {
                    if let path = t.path { WebTab(path: path) } else { MoreView() }
                }
                .tabItem { Label(t.title, systemImage: t.icon) }
                .tag(t)
            }
        }
        .modifier(SidebarOnIPad())
    }
}

/// iPadOS 18's adaptable sidebar for the same tabs; earlier versions keep the tab bar.
private struct SidebarOnIPad: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content.tabViewStyle(.sidebarAdaptable)
        } else {
            content
        }
    }
}

struct SplashView: View {
    var body: some View {
        ZStack {
            Color("LaunchBackground").ignoresSafeArea()
            Image("LaunchLogo").resizable().scaledToFit().frame(width: 96, height: 96)
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
    }
}
