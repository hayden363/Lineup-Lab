import Foundation

/// Small JSON client for the few native calls. Sends the web views' cookies and copies any new ones back.
enum API {
    struct Failure: LocalizedError {
        let message: String
        var status: Int? = nil
        var errorDescription: String? { message }
    }

    @discardableResult
    static func post(_ path: String, _ body: [String: Any]) async throws -> [String: Any] {
        var req = URLRequest(url: Config.url(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await send(req)
    }

    static func get(_ path: String) async throws -> [String: Any] {
        try await send(URLRequest(url: Config.url(path)))
    }

    private static func send(_ request: URLRequest) async throws -> [String: Any] {
        var req = request
        req.timeoutInterval = 30
        req.httpShouldHandleCookies = false                 // the web views' cookie store is the one source of truth
        if let cookie = await WebSession.shared.cookieHeader() {
            req.setValue(cookie, forHTTPHeaderField: "Cookie")
        }
        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw Failure(message: "No response from Lineup Lab.") }
        await WebSession.shared.adopt(cookiesFrom: http)
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        guard (200..<300).contains(http.statusCode) else {
            let detail = json["detail"] as? String
            throw Failure(message: detail ?? "Something went wrong (\(http.statusCode)). Please try again.", status: http.statusCode)
        }
        return json
    }
}
