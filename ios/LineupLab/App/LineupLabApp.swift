import SwiftUI

@main
struct LineupLabApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var auth = AuthManager.shared
    @StateObject private var push = PushManager.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(auth)
                .environmentObject(push)
                .preferredColorScheme(.dark)
                .tint(Color("AccentColor"))
                .task { await auth.refresh() }
        }
    }
}
