import Foundation
import Security

/// A saved copy of the sign-in token in the iOS Keychain, so reopening the app never depends on the web view's cookie
/// store still having it. Stays on this device (no iCloud or backup copy) and is removed on sign-out.
enum SessionVault {
    private static let base: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "com.haydenjohnstonwoods.lineuplab.session",
        kSecAttrAccount as String: Config.sessionCookie,
    ]

    static func load() -> String? {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func save(_ token: String) {
        guard load() != token else { return }
        let data = Data(token.utf8)
        let update: [String: Any] = [kSecValueData as String: data,
                                     kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        if SecItemUpdate(base as CFDictionary, update as CFDictionary) == errSecItemNotFound {
            SecItemAdd(base.merging(update) { _, new in new } as CFDictionary, nil)
        }
    }

    static func clear() {
        SecItemDelete(base as CFDictionary)
    }

    /// iOS keeps Keychain items after an app is deleted. A fresh install must start signed out, and a small marker file
    /// tells the two apart: it lives in the app's own folder, which deleting the app removes.
    static func clearIfFreshInstall() {
        let files = FileManager.default
        guard let folder = files.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else { return }
        let marker = folder.appendingPathComponent("session-vault-ready")
        guard !files.fileExists(atPath: marker.path) else { return }
        clear()
        try? files.createDirectory(at: folder, withIntermediateDirectories: true)
        files.createFile(atPath: marker.path, contents: Data())
    }
}
