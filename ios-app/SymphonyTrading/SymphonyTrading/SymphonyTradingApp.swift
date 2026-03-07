import SwiftUI

@main
struct SymphonyTradingApp: App {
    @StateObject private var apiClient = TradingAPIClient()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(apiClient)
        }
    }
}
