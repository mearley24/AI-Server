import Foundation

final class MarkupSettingsStore: ObservableObject {
    @Published var baseURL: String {
        didSet {
            UserDefaults.standard.set(baseURL, forKey: Self.baseURLKey)
        }
    }
    @Published var teamShareEnabled: Bool {
        didSet {
            UserDefaults.standard.set(teamShareEnabled, forKey: Self.teamShareEnabledKey)
        }
    }

    static let baseURLKey = "markup.base_url.v1"
    static let teamShareEnabledKey = "markup.team_share_enabled.v1"
    static let defaultBaseURL = "http://bobs-mac-mini:8091"

    init() {
        let existing = UserDefaults.standard.string(forKey: Self.baseURLKey) ?? Self.defaultBaseURL
        self.baseURL = existing
        self.teamShareEnabled = UserDefaults.standard.bool(forKey: Self.teamShareEnabledKey)
    }

    var normalizedBaseURL: String {
        var value = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty {
            return Self.defaultBaseURL
        }
        if !value.hasPrefix("http://") && !value.hasPrefix("https://") {
            value = "http://\(value)"
        }
        return value
    }
}

