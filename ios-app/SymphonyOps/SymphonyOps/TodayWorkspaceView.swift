import SwiftUI

struct TodayFocusView: View {
    var mode: TodayWorkspaceMode = .weather
    @State private var quoteIndex = 0
    @AppStorage("weather.setup.enabled.v1") private var weatherSetupEnabled = false
    @AppStorage("weather.location.v1") private var weatherLocation = ""
    @AppStorage("weather.provider.v1") private var weatherProvider = "openweather"

    private static let dailyQuotes = [
        "Make it easy for Future You.",
        "Slow is smooth. Smooth is fast.",
        "One clean handoff beats ten rushed fixes.",
        "Done today is better than perfect someday."
    ]

    var body: some View {
        List {
            switch mode {
            case .weather:
                Section("Weather") {
                    HStack(spacing: 10) {
                        Image(systemName: "cloud.sun.fill")
                            .foregroundColor(.orange)
                        Text("Weather summary")
                            .fontWeight(.semibold)
                    }
                    if weatherSetupEnabled {
                        Text("Configured: \(weatherProviderLabel(weatherProvider)) • \(weatherLocation.isEmpty ? "Location not set" : weatherLocation)")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    } else {
                        Text("Connect weather source in Ops -> Weather.")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            case .schedule:
                Section("Schedule") {
                    HStack(spacing: 10) {
                        Image(systemName: "calendar")
                            .foregroundColor(.blue)
                        Text("Today")
                            .fontWeight(.semibold)
                    }
                    Text("No schedule items loaded yet.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            case .quote:
                Section("Daily Quote") {
                    Text(Self.dailyQuotes[quoteIndex])
                        .font(.body)
                    Button("New Quote") {
                        quoteIndex = Int.random(in: 0..<Self.dailyQuotes.count)
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
        .navigationTitle("Today")
    }

    private func weatherProviderLabel(_ value: String) -> String {
        switch value {
        case "openweather": return "OpenWeather"
        case "weatherapi": return "WeatherAPI"
        default: return "Custom"
        }
    }
}
