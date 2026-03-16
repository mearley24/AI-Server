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
            if mode == .conduit {
                Section("Field Tools") {
                    NavigationLink {
                        ConduitCalculatorPlaceholderView()
                    } label: {
                        Label("Conduit Bend Calculator", systemImage: "ruler")
                    }
                }
            }
        }
        .navigationTitle("Install")
    }
}

private struct ConduitCalculatorPlaceholderView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Conduit Calculator")
                .font(.headline)
            Text("This tool is not available in this app build variant yet.")
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
        .padding()
        .navigationTitle("Conduit Calculator")
    }
}
