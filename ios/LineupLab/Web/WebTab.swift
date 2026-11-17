import SwiftUI

/// A tab (or a pushed screen) showing one page of the site, with a native loading view and offline screen.
struct WebTab: View {
    let path: String
    var title: String? = nil
    @State private var state: WebLoadState = .loading
    @State private var reload = 0
    @EnvironmentObject private var auth: AuthManager

    var body: some View {
        ZStack {
            Color("LaunchBackground").ignoresSafeArea()
            WebView(url: Config.url(path), state: $state, reloadToken: reload + auth.sessionGeneration,
                    onSignedOut: { auth.markSignedOut() })
                .opacity(state == .ready ? 1 : 0.01)
            switch state {
            case .loading:
                VStack(spacing: 14) {
                    Image("LaunchLogo").resizable().scaledToFit().frame(width: 72, height: 72)
                        .clipShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
                    ProgressView().tint(.white)
                }
            case .offline(let why):
                OfflineView(message: why) { state = .loading; reload += 1 }
            case .ready:
                EmptyView()
            }
        }
        .navigationTitle(title ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(title == nil ? .hidden : .visible, for: .navigationBar)
    }
}

struct OfflineView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "wifi.exclamationmark").font(.system(size: 44, weight: .semibold)).foregroundStyle(.secondary)
            Text("Can't reach Lineup Lab").font(.title3.bold())
            Text("Check your connection and try again.\n\(message)")
                .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button("Try again", action: retry).buttonStyle(.borderedProminent).tint(Color("AccentColor"))
        }
        .padding(32)
    }
}
