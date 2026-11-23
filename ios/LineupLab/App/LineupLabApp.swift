import SwiftUI

@main
struct LineupLabApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var auth = AuthManager.shared
    @StateObject private var push = PushManager.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(auth)
                .environmentObject(push)
                .preferredColorScheme(.dark)
                .tint(Color("AccentColor"))
                .task { await auth.refresh() }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active { Task { await auth.refreshIfIncomplete() } }
                }
        }
    }
}
