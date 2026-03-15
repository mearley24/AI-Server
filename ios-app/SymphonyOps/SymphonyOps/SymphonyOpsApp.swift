import SwiftUI

@main
struct SymphonyOpsApp: App {
    @StateObject private var apiClient = APIClient()
    @StateObject private var secretsVault = SecretsVaultStore()
    
    var body: some Scene {
        WindowGroup {
            ContentView(
                availableSections: AppVariant.availableSections,
                defaultSection: AppVariant.defaultSection
            )
                .environmentObject(apiClient)
                .environmentObject(secretsVault)
        }
    }
}
