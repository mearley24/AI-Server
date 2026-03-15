import SwiftUI

struct InstallWorkspaceView: View {
    var mode: InstallWorkspaceMode = .queue

    var body: some View {
        List {
            if mode == .queue {
                Section("Field Execution") {
                    NavigationLink {
                        ServicesView()
                    } label: {
                        Label("Service + Install Queue", systemImage: "wrench.and.screwdriver")
                    }
                }
            }
        }
        .navigationTitle("Install")
    }
}
