import SwiftUI

struct SuiteAppsHubView: View {
    var mode: AppsHubMode = .daily
    var onOpen: (AppSection) -> Void

    var body: some View {
        List {
            Section("Symphony Suite") {
                Text("SymphonyOps is your launcher for daily work apps. Choose a workspace below.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            if mode == .daily || mode == .all {
                Section("Daily Apps") {
                    launcherRow(
                        title: "Projects",
                        subtitle: "SOW, Markup, and Manual Digest",
                        icon: "folder.badge.gearshape",
                        color: .orange
                    ) { onOpen(.projects) }

                    launcherRow(
                        title: "Sales",
                        subtitle: "D-Tools product agent and pipeline",
                        icon: "dollarsign.circle",
                        color: .green
                    ) { onOpen(.sales) }

                    launcherRow(
                        title: "Install",
                        subtitle: "Field queue and execution workflows",
                        icon: "wrench.and.screwdriver",
                        color: .blue
                    ) { onOpen(.install) }

                    launcherRow(
                        title: "Ops",
                        subtitle: "Dropout watcher, health, and automation",
                        icon: "server.rack",
                        color: .purple
                    ) { onOpen(.ops) }
                }
            }

            if mode == .all {
                Section("Support Apps") {
                    launcherRow(
                        title: "Today",
                        subtitle: "Weather, schedule, and daily focus",
                        icon: "sun.max",
                        color: .yellow
                    ) { onOpen(.today) }

                    launcherRow(
                        title: "Settings",
                        subtitle: "Connection, auth, and preferences",
                        icon: "gearshape",
                        color: .gray
                    ) { onOpen(.settings) }
                }
            }
        }
        .navigationTitle("Apps")
    }

    @ViewBuilder
    private func launcherRow(
        title: String,
        subtitle: String,
        icon: String,
        color: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .foregroundColor(color)
                    .font(.title3)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundColor(.primary)
                    Text(subtitle)
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
    }
}

enum AppSection: Int, CaseIterable, Identifiable {
    case apps
    case today
    case projects
    case sales
    case install
    case ops
    case settings

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .apps: return "Apps"
        case .today: return "Today"
        case .projects: return "Projects"
        case .sales: return "Sales"
        case .install: return "Install"
        case .ops: return "Ops"
        case .settings: return "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .apps: return "square.grid.2x2"
        case .today: return "sun.max"
        case .projects: return "folder"
        case .sales: return "person.3"
        case .install: return "wrench.and.screwdriver"
        case .ops: return "server.rack"
        case .settings: return "gear"
        }
    }
}

enum AppsHubMode: Int {
    case daily
    case all
}

enum ProjectsWorkspaceMode: Int {
    case markup
    case sow
    case manualDigest
    case roomModeler
}

enum TodayWorkspaceMode: Int {
    case weather
    case schedule
    case quote
}

enum SalesWorkspaceMode: Int {
    case pipeline
    case dtoolsAgent
}

enum InstallWorkspaceMode: Int {
    case queue
}

enum OpsWorkspaceMode: Int {
    case health
    case dropout
    case notes
    case weather
}
