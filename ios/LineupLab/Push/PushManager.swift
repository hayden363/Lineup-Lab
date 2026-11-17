import SwiftUI
import UserNotifications

/// Push notifications (engine/push.py sends them): permission, the APNs device token, and taps.
/// Version 1 sends the daily "today's Daily Drive is live" reminder; a tapped notification opens its `url` path.
@MainActor
final class PushManager: NSObject, ObservableObject {
    static let shared = PushManager()

    @Published var authorization: UNAuthorizationStatus = .notDetermined
    /// Path from a tapped notification (e.g. "/play"); RootView switches to the matching tab.
    @Published var openPath: String?
    @AppStorage("push.driveReminder") var driveReminder = true

    private var token: String?
    private let defaults = UserDefaults.standard

    #if DEBUG
    private let environment = "sandbox"
    #else
    private let environment = "production"
    #endif

    func refreshAuthorization() async {
        authorization = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// Asks once (after sign-in, from the welcome flow), then registers with APNs if allowed.
    func requestPermission() async {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        await refreshAuthorization()
        if granted { UIApplication.shared.registerForRemoteNotifications() }
    }

    func registerIfAllowed() async {
        await refreshAuthorization()
        if authorization == .authorized || authorization == .provisional {
            UIApplication.shared.registerForRemoteNotifications()
        }
    }

    func didRegister(deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        token = hex
        Task { await upload() }
    }

    /// Sends the token (and the reminder preference) to the server for the signed-in account.
    func upload() async {
        guard let token, AuthManager.shared.status == .signedIn else { return }
        _ = try? await API.post("/api/push/register",
                                ["token": token, "environment": environment, "drive_reminder": driveReminder])
    }

    func unregister() async {
        guard let token else { return }
        _ = try? await API.post("/api/push/unregister", ["token": token])
    }
}

extension PushManager: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let path = response.notification.request.content.userInfo["url"] as? String
        Task { @MainActor in
            if let path { PushManager.shared.openPath = path }
            completionHandler()
        }
    }
}

/// UIKit hooks SwiftUI doesn't expose: APNs registration callbacks and the notification delegate.
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = PushManager.shared
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in PushManager.shared.didRegister(deviceToken: deviceToken) }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        print("[push] APNs registration failed: \(error.localizedDescription)")
    }
}
