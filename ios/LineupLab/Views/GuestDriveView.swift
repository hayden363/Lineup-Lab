import SwiftUI

/// The Daily Drive without an account (it works signed out, so the app doesn't force sign-in to play: Guideline 5.1.1).
struct GuestDriveView: View {
    var onSignIn: () -> Void

    var body: some View {
        NavigationStack {
            WebTab(path: "/play", title: "The Daily Drive")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Sign in", action: onSignIn)
                    }
                }
        }
    }
}
