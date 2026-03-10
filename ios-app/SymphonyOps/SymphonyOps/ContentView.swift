import SwiftUI
import WebKit
import UniformTypeIdentifiers
import UIKit
import os

struct ContentView: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var selectedTab = 0
    @State private var selectedSection: AppSection = .home
    @State private var didRunStartup = false
    @State private var sidebarQuery = ""
    @StateObject private var secretsVault = SecretsVaultStore()
    private let perfLogger = Logger(subsystem: "com.symphonysh.SymphonyOps", category: "perf")
    
    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                NavigationSplitView {
                    List(filteredSections) { section in
                        Button {
                            selectedSection = section
                        } label: {
                            HStack {
                                Label(section.title, systemImage: section.systemImage)
                                Spacer()
                                if selectedSection == section {
                                    Image(systemName: "checkmark")
                                        .foregroundColor(.secondary)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                    .listStyle(.sidebar)
                    .searchable(text: $sidebarQuery, placement: .sidebar, prompt: "Search")
                    .navigationTitle("Symphony Ops")
                    .toolbar {
                        ToolbarItem(placement: .topBarLeading) {
                            Button("Edit") {}
                                .disabled(true)
                        }
                        ToolbarItem(placement: .topBarTrailing) {
                            Image(systemName: "circle.grid.2x2")
                        }
                    }
                } detail: {
                    sectionView(for: selectedSection)
                }
            } else {
                TabView(selection: $selectedTab) {
                    DashboardView()
                        .tabItem {
                            Label("Home", systemImage: "house")
                        }
                        .tag(0)
                    
                    AIChatView()
                        .tabItem {
                            Label("Ask Bob", systemImage: "bubble.left.and.bubble.right")
                        }
                        .tag(1)

                    ActionsView()
                        .tabItem {
                            Label("Work", systemImage: "checklist")
                        }
                        .tag(2)
                    
                    LeadsView()
                        .tabItem {
                            Label("Leads", systemImage: "person.3")
                        }
                        .tag(3)
                    
                    OpsHubView()
                        .environmentObject(secretsVault)
                        .tabItem {
                            Label("Ops", systemImage: "square.grid.2x2")
                        }
                        .tag(4)
                }
            }
        }
        .accentColor(Color.orange)
        .task {
            await runStartupIfNeeded()
        }
    }

    private var filteredSections: [AppSection] {
        let q = sidebarQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return AppSection.allCases }
        return AppSection.allCases.filter { section in
            section.title.lowercased().contains(q)
        }
    }

    @ViewBuilder
    private func sectionView(for section: AppSection) -> some View {
        switch section {
        case .home:
            DashboardView()
        case .askBob:
            AIChatView()
        case .work:
            ActionsView()
        case .leads:
            LeadsView()
        case .ops:
            OpsHubView()
                .environmentObject(secretsVault)
        }
    }

    @MainActor
    private func runStartupIfNeeded() async {
        if didRunStartup { return }
        didRunStartup = true
        let startupStart = Date()

        // Start fast: lightweight connection check first.
        await api.checkConnection()
        perfLogger.info("startup.checkConnection.ms=\(Int(Date().timeIntervalSince(startupStart) * 1000))")

        // Load heavy startup tasks concurrently without blocking UI responsiveness.
        let heavyStart = Date()
        let isConnectedNow = api.isConnected
        async let dashboardTask: Void = {
            if isConnectedNow {
                await api.fetchDashboard()
            }
        }()
        async let ollamaTask: Void = api.checkOllama()
        async let lmTask: Void = api.checkLMStudio()
        async let aiStatusTask: Void = api.fetchAIStatus()
        _ = await (dashboardTask, ollamaTask, lmTask, aiStatusTask)
        perfLogger.info("startup.heavyTasks.ms=\(Int(Date().timeIntervalSince(heavyStart) * 1000))")
        perfLogger.info("startup.total.ms=\(Int(Date().timeIntervalSince(startupStart) * 1000))")
    }
}

private enum AppSection: Int, CaseIterable, Identifiable {
    case home
    case askBob
    case work
    case leads
    case ops

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .home: return "Home"
        case .askBob: return "Ask Bob"
        case .work: return "Work"
        case .leads: return "Leads"
        case .ops: return "Ops"
        }
    }

    var systemImage: String {
        switch self {
        case .home: return "house"
        case .askBob: return "bubble.left.and.bubble.right"
        case .work: return "checklist"
        case .leads: return "person.3"
        case .ops: return "square.grid.2x2"
        }
    }
}

struct OpsHubView: View {
    @EnvironmentObject var secretsVault: SecretsVaultStore
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                opsList
            } else {
                NavigationStack {
                    opsList
                }
            }
        }
    }

    private var opsList: some View {
        List {
            Section("Operations") {
                    NavigationLink {
                        ClaudeApprovalView()
                    } label: {
                        Label("Claude Approvals", systemImage: "brain.head.profile")
                    }
                    NavigationLink {
                        MissionControlWebView()
                    } label: {
                        Label("Mission Control", systemImage: "antenna.radiowaves.left.and.right")
                    }
                    NavigationLink {
                        NeuralMapWebView()
                    } label: {
                        Label("Neural Map", systemImage: "brain")
                    }
                }

            Section("Data") {
                    NavigationLink {
                        FactsView()
                    } label: {
                        Label("Facts Queue", systemImage: "doc.text.fill")
                    }
                    NavigationLink {
                        SecretsVaultView()
                            .environmentObject(secretsVault)
                    } label: {
                        Label("Secrets Vault", systemImage: "lock.shield")
                    }
                }

            Section("Configuration") {
                    NavigationLink {
                        SettingsView()
                    } label: {
                        Label("Settings", systemImage: "gear")
                    }
            }
            .navigationTitle("Ops Hub")
        }
    }
}

// MARK: - Dashboard View

private struct ActionResultEntry: Codable {
    let message: String
    let updatedAt: TimeInterval
}

struct DashboardView: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var quickActionResult: String?
    @State private var quickActionLoading = false
    @State private var primaryActionResults: [String: ActionResultEntry] = [:]
    @State private var selectedPrimaryAction: String? = nil
    @AppStorage("home.primaryActionResults.v1") private var persistedPrimaryActionResults = ""
    @AppStorage("home.selectedPrimaryAction.v1") private var persistedSelectedPrimaryAction = ""
    @State private var taskTitle = ""
    @State private var taskDescription = ""
    @State private var taskType = "research"
    @State private var taskPriority = "medium"
    @State private var homeClaudePending: [ClaudeTask] = []
    @State private var homeNotesApprovals: [NotesTaskApprovalItem] = []
    @State private var taskBoardLoading = false
    @State private var showTaskUploadImporter = false
    @State private var showProjectBundleImporter = false
    @State private var uploadCategory = "proposal"
    @State private var uploadProjectName = ""
    @State private var uploadClientName = ""
    @State private var uploadAddressLine = ""
    @State private var uploadLocationName = ""
    @State private var uploadWatchFolderPath = ""
    @State private var uploadDiscipline = ""
    @State private var uploadSheetNumber = ""
    @State private var uploadRevision = ""
    @State private var uploadIssueDate = ""
    @State private var uploadsQueue: [UploadQueueItem] = []
    @State private var projectWatches: [ProjectWatchItem] = []
    @State private var projectSummaries: [String: ProjectSummaryPayload] = [:]
    @State private var showApprovalsPanel = true
    @State private var showTaskCreatePanel = false
    @State private var showUploadPanel = false
    @State private var showMoreActionsPanel = false
    @State private var showUploadsQueuePanel = true
    @State private var showProjectWatchesPanel = true
    @State private var didInitialDashboardLoad = false
    private let perfLogger = Logger(subsystem: "com.symphonysh.SymphonyOps", category: "perf")
    
    private var dashboardHorizontalPadding: CGFloat {
        horizontalSizeClass == .regular ? 28 : 20
    }

    private var primaryActionColumns: [GridItem] {
        if horizontalSizeClass == .regular {
            return Array(repeating: GridItem(.flexible(), spacing: 12), count: 4)
        }
        return Array(repeating: GridItem(.flexible(), spacing: 12), count: 2)
    }
    
    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 20) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Today")
                            .font(.title2)
                            .fontWeight(.bold)
                        Text("Start with high-impact actions, then intake and approvals.")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)

                    StatusPill(
                        isConnected: api.isConnected,
                        ollamaAvailable: api.ollamaAvailable,
                        lmStudioAvailable: api.lmStudioAvailable,
                        onRetry: { Task {
                await api.checkOllama()
                await api.checkLMStudio()
                await api.fetchAIStatus()
            } }
                    )
                    .padding(.horizontal, 20)

                    if let guidance = nextBestAction {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Next Best Action")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundColor(.secondary)
                            Text(guidance.title)
                                .font(.headline)
                            Text(guidance.detail)
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                            Button(guidance.cta) {
                                Task { await runNextBestAction() }
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                        .background(Color(.secondarySystemGroupedBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .padding(.horizontal, 20)
                    }

                    // Focus actions first
                    LazyVGrid(columns: primaryActionColumns, spacing: 12) {
                        PrimaryActionCard(
                            title: "Morning",
                            subtitle: "Run startup checklist",
                            icon: "sunrise.fill",
                            color: Color(red: 1, green: 0.85, blue: 0.4),
                            isSelected: selectedPrimaryAction == "Morning",
                            isLoading: quickActionLoading && selectedPrimaryAction == "Morning",
                            statusLabel: actionFreshness("Morning")?.label,
                            statusColor: actionFreshness("Morning")?.color
                        ) {
                            Task { await runQuickAction(name: "Morning") { await api.runMorningChecklist() } }
                        }
                        .disabled(quickActionLoading)
                        
                        PrimaryActionCard(
                            title: "Check Bids",
                            subtitle: "Scan incoming opportunities",
                            icon: "hammer.fill",
                            color: Color(red: 0.35, green: 0.55, blue: 0.95),
                            isSelected: selectedPrimaryAction == "Bids",
                            isLoading: quickActionLoading && selectedPrimaryAction == "Bids",
                            statusLabel: actionFreshness("Bids")?.label,
                            statusColor: actionFreshness("Bids")?.color
                        ) {
                            Task { await runQuickAction(name: "Bids") { await api.checkBids() } }
                        }
                        .disabled(quickActionLoading)
                        
                        PrimaryActionCard(
                            title: "Website",
                            subtitle: "Check site uptime",
                            icon: "globe.americas.fill",
                            color: Color(red: 0.3, green: 0.7, blue: 0.5),
                            isSelected: selectedPrimaryAction == "Website",
                            isLoading: quickActionLoading && selectedPrimaryAction == "Website",
                            statusLabel: actionFreshness("Website")?.label,
                            statusColor: actionFreshness("Website")?.color
                        ) {
                            Task { await runWebsiteAction() }
                        }
                        .disabled(quickActionLoading)
                        
                        PrimaryActionCard(
                            title: "Markup",
                            subtitle: "Open drawing workspace",
                            icon: "pencil.and.outline",
                            color: Color(red: 0.95, green: 0.6, blue: 0.3),
                            isSelected: selectedPrimaryAction == "Markup",
                            isLoading: false,
                            statusLabel: actionFreshness("Markup")?.label,
                            statusColor: actionFreshness("Markup")?.color
                        ) {
                            selectedPrimaryAction = "Markup"
                            setPrimaryActionResult("Markup", message: "Opened Markup workspace.")
                            let url = api.markupURL ?? api.fallbackMarkupURL
                            Task {
                                _ = await UIApplication.shared.open(url)
                            }
                        }
                    }
                    .padding(.horizontal, dashboardHorizontalPadding)

                    if !primaryActionResults.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Action Results")
                                .font(.headline)
                                .fontWeight(.semibold)

                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 8) {
                                    ForEach(["Morning", "Bids", "Website", "Markup"], id: \.self) { action in
                                        if primaryActionResults[action] != nil {
                                            Button(action) {
                                                selectedPrimaryAction = action
                                                persistedSelectedPrimaryAction = action
                                            }
                                            .buttonStyle(.borderedProminent)
                                            .tint(selectedPrimaryAction == action ? .orange : .gray.opacity(0.4))
                                            .controlSize(.small)
                                        }
                                    }
                                }
                            }

                            if let selected = selectedPrimaryAction, let result = primaryActionResults[selected] {
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack {
                                        Text(selected)
                                            .font(.subheadline)
                                            .fontWeight(.semibold)
                                        Spacer()
                                        Text(relativeTimeString(from: result.updatedAt))
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                    }
                                    if quickActionLoading && (selected == "Morning" || selected == "Bids" || selected == "Website") {
                                        HStack(spacing: 8) {
                                            ProgressView().scaleEffect(0.9)
                                            Text("Running...")
                                                .font(.caption)
                                                .foregroundColor(.secondary)
                                        }
                                    } else {
                                        Text(result.message)
                                            .font(.subheadline)
                                            .foregroundColor(.secondary)
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(14)
                                .background(Color(.secondarySystemGroupedBackground))
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                            }
                        }
                        .padding(.horizontal, 20)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("Inbox")
                                .font(.headline)
                                .fontWeight(.semibold)
                            Spacer()
                            Button {
                                Task { await refreshHomeTaskBoard() }
                            } label: {
                                Label("Refresh", systemImage: "arrow.clockwise")
                                    .font(.caption)
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .disabled(taskBoardLoading)
                        }

                        HStack {
                            Label("\(homeClaudePending.count) Claude approvals", systemImage: "brain.head.profile")
                                .font(.caption)
                                .foregroundColor(homeClaudePending.isEmpty ? .secondary : .primary)
                            Spacer()
                            Label("\(homeNotesApprovals.count) note approvals", systemImage: "doc.badge.clock")
                                .font(.caption)
                                .foregroundColor(homeNotesApprovals.isEmpty ? .secondary : .primary)
                        }

                        DisclosureGroup(isExpanded: $showApprovalsPanel) {
                            if homeClaudePending.isEmpty && homeNotesApprovals.isEmpty {
                                Text("No pending approvals.")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }

                            if !homeClaudePending.isEmpty {
                                Text("Claude approvals")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                ForEach(homeClaudePending.prefix(3)) { task in
                                    HStack {
                                        Text(task.title)
                                            .font(.caption2)
                                            .lineLimit(1)
                                        Spacer()
                                        Button("Approve") {
                                            Task { await approveHomeClaudeTask(task) }
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .controlSize(.mini)
                                    }
                                }
                            }

                            if !homeNotesApprovals.isEmpty {
                                Text("Note approvals")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                ForEach(homeNotesApprovals.prefix(3)) { item in
                                    HStack {
                                        Text(item.note_title ?? "Untitled note")
                                            .font(.caption2)
                                            .lineLimit(1)
                                        Spacer()
                                        Button("Approve") {
                                            Task { await approveHomeNoteTask(item.id) }
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .controlSize(.mini)
                                    }
                                }
                            }
                        } label: {
                            Label("Approvals", systemImage: "checkmark.seal")
                                .font(.subheadline)
                        }

                        DisclosureGroup(isExpanded: $showTaskCreatePanel) {
                            TextField("New task title", text: $taskTitle)
                                .textFieldStyle(.roundedBorder)
                            TextField("Details (optional)", text: $taskDescription)
                                .textFieldStyle(.roundedBorder)

                            HStack {
                                Menu {
                                    Button("Research") { taskType = "research" }
                                    Button("Proposal") { taskType = "proposal" }
                                    Button("Troubleshooting") { taskType = "troubleshooting" }
                                    Button("Documentation") { taskType = "documentation" }
                                    Button("Integration") { taskType = "integration" }
                                    Button("Claude (approval)") { taskType = "claude" }
                                } label: {
                                    Label("Type: \(taskType)", systemImage: "tag")
                                        .font(.caption)
                                }
                                .buttonStyle(.bordered)

                                Menu {
                                    Button("Critical") { taskPriority = "critical" }
                                    Button("High") { taskPriority = "high" }
                                    Button("Medium") { taskPriority = "medium" }
                                    Button("Low") { taskPriority = "low" }
                                } label: {
                                    Label("Priority: \(taskPriority)", systemImage: "flag")
                                        .font(.caption)
                                }
                                .buttonStyle(.bordered)

                                Spacer()
                                Button("Create") {
                                    Task { await createHomeTask() }
                                }
                                .buttonStyle(.borderedProminent)
                                .disabled(taskTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || taskBoardLoading)
                            }
                        } label: {
                            Label("Create Task", systemImage: "plus.circle")
                                .font(.subheadline)
                        }

                        DisclosureGroup(isExpanded: $showUploadPanel) {
                            HStack {
                                Menu {
                                    Button("Proposal") { uploadCategory = "proposal" }
                                    Button("Drawing") { uploadCategory = "drawing" }
                                    Button("Image") { uploadCategory = "image" }
                                    Button("Document") { uploadCategory = "document" }
                                } label: {
                                    Label("Category: \(uploadCategory.capitalized)", systemImage: "folder")
                                        .font(.caption)
                                }
                                .buttonStyle(.bordered)

                                Spacer()
                                Button("Upload File") {
                                    showTaskUploadImporter = true
                                }
                                .buttonStyle(.borderedProminent)
                                .disabled(taskBoardLoading)
                                Button("Upload Project ZIP") {
                                    showProjectBundleImporter = true
                                }
                                .buttonStyle(.bordered)
                                .disabled(taskBoardLoading)
                            }

                            TextField("Project name", text: $uploadProjectName)
                                .textFieldStyle(.roundedBorder)
                            TextField("Client name", text: $uploadClientName)
                                .textFieldStyle(.roundedBorder)
                            TextField("Address (# + street)", text: $uploadAddressLine)
                                .textFieldStyle(.roundedBorder)
                            TextField("Location (city/town/suburb)", text: $uploadLocationName)
                                .textFieldStyle(.roundedBorder)
                            TextField("Watch folder path on server (optional)", text: $uploadWatchFolderPath)
                                .textFieldStyle(.roundedBorder)
                            Text("If set, new files dropped into this folder auto-ingest into project knowledge.")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            if uploadCategory == "drawing" {
                                TextField("Discipline (e.g., AV, ELEC, LOW-VOLT)", text: $uploadDiscipline)
                                    .textFieldStyle(.roundedBorder)
                                HStack {
                                    TextField("Sheet # (e.g., A1.2)", text: $uploadSheetNumber)
                                        .textFieldStyle(.roundedBorder)
                                    TextField("Rev (e.g., 3)", text: $uploadRevision)
                                        .textFieldStyle(.roundedBorder)
                                }
                                TextField("Issue date (YYYY-MM-DD)", text: $uploadIssueDate)
                                    .textFieldStyle(.roundedBorder)
                            }

                            Text("Naming v2: Mitchell - 182 Stage Coach Way - Singletree + metadata suffix")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        } label: {
                            Label("Upload Intake", systemImage: "square.and.arrow.up")
                                .font(.subheadline)
                        }

                        DisclosureGroup(isExpanded: $showUploadsQueuePanel) {
                            if uploadsQueue.isEmpty {
                                Text("No recent uploads yet.")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            } else {
                                ForEach(uploadsQueue.prefix(10)) { item in
                                    HStack(alignment: .top, spacing: 8) {
                                        Circle()
                                            .fill(statusColor(item.open_complete_status))
                                            .frame(width: 8, height: 8)
                                            .padding(.top, 5)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(item.stored_filename)
                                                .font(.caption2)
                                                .lineLimit(1)
                                            Text("#\(item.task_id ?? 0) • \(item.task_status) • \(item.open_complete_status.capitalized)")
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                        }
                                        Spacer()
                                    }
                                }
                            }
                        } label: {
                            Label("Uploads Queue (last 10)", systemImage: "tray.full")
                                .font(.subheadline)
                        }

                        DisclosureGroup(isExpanded: $showProjectWatchesPanel) {
                            HStack {
                                Button("Run Scan Now") {
                                    Task { await runWatchScanNow() }
                                }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                                .disabled(taskBoardLoading)

                                Button("Discover New Projects") {
                                    Task { await discoverProjectWatchesNow() }
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                                .disabled(taskBoardLoading)
                            }

                            if projectWatches.isEmpty {
                                Text("No project watches yet.")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            } else {
                                ForEach(projectWatches.prefix(6)) { watch in
                                    VStack(alignment: .leading, spacing: 3) {
                                        HStack {
                                            Circle()
                                                .fill((watch.enabled ? Color.green : Color.gray))
                                                .frame(width: 8, height: 8)
                                            Text(watch.project_name ?? "Project")
                                                .font(.caption)
                                                .fontWeight(.semibold)
                                            Spacer()
                                            if let taskId = watch.task_id {
                                                Text("Task #\(taskId)")
                                                    .font(.caption2)
                                                    .foregroundColor(.secondary)
                                            }
                                        }
                                        Text("Last scan: \(watch.last_scan_at ?? "never") • processed \(watch.last_processed_count ?? 0)")
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                        if let slug = watch.project_slug, let summary = projectSummaries[slug] {
                                            Text("Signals • RFI \(summary.signals?.rfi_tags?.count ?? 0) • Wants/Needs \(summary.signals?.wants_needs_tags?.count ?? 0)")
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                        }
                                        if let err = watch.last_error, !err.isEmpty {
                                            Text("⚠️ \(err)")
                                                .font(.caption2)
                                                .foregroundColor(.orange)
                                        }
                                    }
                                    .padding(.vertical, 3)
                                }
                            }
                        } label: {
                            Label("Project Watches", systemImage: "eye")
                                .font(.subheadline)
                        }
                    }
                    .padding(14)
                    .background(Color(.secondarySystemGroupedBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .padding(.horizontal, 20)
                    .fileImporter(
                        isPresented: $showTaskUploadImporter,
                        allowedContentTypes: [.pdf, .image, .plainText, .commaSeparatedText, .data],
                        allowsMultipleSelection: false
                    ) { result in
                        switch result {
                        case .success(let urls):
                            guard let url = urls.first else { return }
                            Task { await uploadTaskIntakeFile(url) }
                        case .failure(let err):
                            quickActionResult = "❌ Upload picker failed: \(err.localizedDescription)"
                        }
                    }
                    .fileImporter(
                        isPresented: $showProjectBundleImporter,
                        allowedContentTypes: [.archive, .data],
                        allowsMultipleSelection: false
                    ) { result in
                        switch result {
                        case .success(let urls):
                            guard let url = urls.first else { return }
                            Task { await uploadProjectBundleFile(url) }
                        case .failure(let err):
                            quickActionResult = "❌ ZIP picker failed: \(err.localizedDescription)"
                        }
                    }

                    if let stats = api.stats {
                        CompactStatsBar(
                            proposals: stats.proposals.draft + stats.proposals.sent,
                            knowledge: stats.cortex.articles,
                            cost: Int(stats.subscriptions.monthly_total),
                            servicesUp: api.services.filter { $0.isRunning }.count,
                            servicesTotal: api.services.count
                        )
                        .padding(.horizontal, 20)
                    }

                    DisclosureGroup(isExpanded: $showMoreActionsPanel) {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Social")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundColor(.secondary)
                            HStack(spacing: 10) {
                                ToolChip(title: "Story Tweet", icon: "book.fill") {
                                    Task { await runSocialAction("Story") { await api.socialStory() } }
                                }
                                .disabled(quickActionLoading)
                                ToolChip(title: "Tip Tweet", icon: "lightbulb.fill") {
                                    Task { await runSocialAction("Tip") { await api.socialTip() } }
                                }
                                .disabled(quickActionLoading)
                                ToolChip(title: "Post Next", icon: "paperplane.fill") {
                                    Task { await runSocialAction("Post") { await api.socialXPost() } }
                                }
                                .disabled(quickActionLoading)
                            }

                            Text("Diagnostics")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundColor(.secondary)
                            HStack(spacing: 10) {
                                ToolChip(title: "Verify Ollama", icon: "checkmark.shield.fill") {
                                    Task { await runVerifyOllama() }
                                }
                                .disabled(quickActionLoading)
                                ToolChip(title: "Verify LM Studio", icon: "checkmark.shield.fill") {
                                    Task { await runVerifyLMStudio() }
                                }
                                .disabled(quickActionLoading)
                            }
                        }
                    } label: {
                        Label("More Actions", systemImage: "ellipsis.circle")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                            .foregroundColor(.secondary)
                            .padding(.horizontal, 4)
                    }
                    .padding(.horizontal, 20)

                    if quickActionLoading {
                        HStack(spacing: 8) {
                            ProgressView()
                                .scaleEffect(0.9)
                            Text("Running…")
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                    }
                    
                    if let result = quickActionResult {
                        ResultCard(text: result) {
                            quickActionResult = nil
                        }
                        .padding(.horizontal, 20)
                    }
                    
                    if let error = api.error {
                        Text(error)
                            .font(.subheadline)
                            .foregroundColor(.red)
                            .padding(.horizontal, 20)
                    }
                }
                .padding(.vertical, 24)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Symphony Ops")
            .refreshable {
                await api.fetchDashboard()
                await api.fetchAIStatus(force: true)
                await refreshHomeTaskBoard()
            }
            .task {
                guard !didInitialDashboardLoad else { return }
                didInitialDashboardLoad = true
                let loadStart = Date()
                async let markupTask: Void = api.fetchMarkupURL()
                async let taskBoardTask: Void = refreshHomeTaskBoard()
                _ = await (markupTask, taskBoardTask)
                perfLogger.info("dashboard.initialLoad.ms=\(Int(Date().timeIntervalSince(loadStart) * 1000))")
            }
            .onAppear {
                restorePrimaryActionResults()
                if selectedPrimaryAction == nil, !persistedSelectedPrimaryAction.isEmpty {
                    selectedPrimaryAction = persistedSelectedPrimaryAction
                }
                Task { await api.fetchAIStatus() }
            }
        }
    }
    
    func runQuickAction(name: String, action: () async -> CommandResult?) async {
        selectedPrimaryAction = name
        persistedSelectedPrimaryAction = name
        quickActionLoading = true
        quickActionResult = nil
        let result = await action()
        let message = result?.output ?? result?.error ?? (result?.success == true ? "Done" : "Failed")
        setPrimaryActionResult(name, message: message)
        quickActionResult = message
        quickActionLoading = false
    }
    
    func runWebsiteAction() async {
        selectedPrimaryAction = "Website"
        persistedSelectedPrimaryAction = "Website"
        quickActionLoading = true
        quickActionResult = nil
        let result = await api.checkWebsite()
        let message: String
        if let status = result {
            let upCount = status.sites.values.filter { $0.uptime.status == "up" }.count
            let total = status.sites.count
            message = "\(upCount)/\(total) sites up"
        } else {
            message = api.error ?? "Failed"
        }
        setPrimaryActionResult("Website", message: message)
        quickActionResult = message
        quickActionLoading = false
    }

    func setPrimaryActionResult(_ action: String, message: String) {
        primaryActionResults[action] = ActionResultEntry(
            message: message,
            updatedAt: Date().timeIntervalSince1970
        )
        persistPrimaryActionResults()
    }

    func persistPrimaryActionResults() {
        guard let data = try? JSONEncoder().encode(primaryActionResults),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        persistedPrimaryActionResults = json
    }

    func restorePrimaryActionResults() {
        guard !persistedPrimaryActionResults.isEmpty,
              let data = persistedPrimaryActionResults.data(using: .utf8),
              let decoded = try? JSONDecoder().decode([String: ActionResultEntry].self, from: data) else {
            return
        }
        primaryActionResults = decoded
        if selectedPrimaryAction == nil, !persistedSelectedPrimaryAction.isEmpty {
            selectedPrimaryAction = persistedSelectedPrimaryAction
        }
    }

    func relativeTimeString(from timestamp: TimeInterval) -> String {
        let date = Date(timeIntervalSince1970: timestamp)
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }

    func actionFreshness(_ action: String) -> (label: String, color: Color)? {
        guard let entry = primaryActionResults[action] else { return nil }
        let age = Date().timeIntervalSince1970 - entry.updatedAt
        if age < 4 * 3600 {
            return ("Fresh", .green)
        }
        if age < 12 * 3600 {
            return ("Needs refresh", .orange)
        }
        return ("Stale", .red)
    }

    var nextBestAction: (title: String, detail: String, cta: String)? {
        if !homeClaudePending.isEmpty || !homeNotesApprovals.isEmpty {
            return (
                "Clear pending approvals",
                "You have \(homeClaudePending.count + homeNotesApprovals.count) approvals waiting.",
                "Review Approvals"
            )
        }
        let openUploads = uploadsQueue.filter { $0.open_complete_status.lowercased() == "open" }.count
        if openUploads > 0 {
            return (
                "Process upload queue",
                "\(openUploads) uploads are still open and linked to tasks.",
                "Open Uploads Queue"
            )
        }
        let stalledWatches = projectWatches.filter { ($0.last_processed_count ?? 0) == 0 && ($0.scan_in_progress ?? false) == false }
        if !stalledWatches.isEmpty {
            return (
                "Run project watch scan",
                "\(stalledWatches.count) watches have no recent new items. Run a scan check.",
                "Run Watch Scan"
            )
        }
        if primaryActionResults["Morning"] == nil {
            return ("Run morning checklist", "Kick off the day with your standard startup flow.", "Run Morning")
        }
        if actionFreshness("Morning")?.label == "Stale" || actionFreshness("Morning")?.label == "Needs refresh" {
            return ("Refresh morning checklist", "Your morning status is out of date.", "Run Morning")
        }
        if primaryActionResults["Bids"] == nil {
            return ("Check new bids", "Make sure no opportunities are waiting.", "Check Bids")
        }
        if actionFreshness("Bids")?.label == "Stale" || actionFreshness("Bids")?.label == "Needs refresh" {
            return ("Refresh bid scan", "Your bid scan is getting stale.", "Check Bids")
        }
        if primaryActionResults["Website"] == nil {
            return ("Check website health", "Run uptime checks for your sites.", "Check Website")
        }
        if actionFreshness("Website")?.label == "Stale" || actionFreshness("Website")?.label == "Needs refresh" {
            return ("Refresh website health", "Website status is stale.", "Check Website")
        }
        return ("Open Markup", "Continue room and symbol work on active drawings.", "Open Markup")
    }

    func runNextBestAction() async {
        guard let guidance = nextBestAction else { return }
        switch guidance.cta {
        case "Review Approvals":
            showApprovalsPanel = true
        case "Open Uploads Queue":
            showUploadsQueuePanel = true
        case "Run Watch Scan":
            await runWatchScanNow()
        case "Run Morning":
            await runQuickAction(name: "Morning") { await api.runMorningChecklist() }
        case "Check Bids":
            await runQuickAction(name: "Bids") { await api.checkBids() }
        case "Check Website":
            await runWebsiteAction()
        default:
            selectedPrimaryAction = "Markup"
            persistedSelectedPrimaryAction = "Markup"
            setPrimaryActionResult("Markup", message: "Opened Markup workspace.")
            let url = api.markupURL ?? api.fallbackMarkupURL
            _ = await UIApplication.shared.open(url)
        }
    }

    func runSocialAction(_ name: String, action: () async -> CommandResult?) async {
        quickActionLoading = true
        quickActionResult = nil
        let result = await action()
        quickActionResult = result?.output ?? result?.error ?? (result?.success == true ? "✅ \(name) done" : "❌ Failed")
        quickActionLoading = false
    }
    
    func runVerifyOllama() async {
        quickActionLoading = true
        quickActionResult = nil
        let (ok, msg) = await api.verifyOllama()
        quickActionResult = ok ? "✅ \(msg)" : "❌ \(msg)"
        quickActionLoading = false
    }

    func runVerifyLMStudio() async {
        quickActionLoading = true
        quickActionResult = nil
        let (ok, msg) = await api.verifyLMStudio()
        quickActionResult = ok ? "✅ \(msg)" : "❌ \(msg)"
        quickActionLoading = false
    }

    func refreshHomeTaskBoard() async {
        taskBoardLoading = true
        async let claude = api.fetchClaudePendingTasks()
        async let approvals = api.fetchNotesTaskApprovals(status: "pending_approval", limit: 8)
        async let uploads = api.fetchUploadsQueue(limit: 10)
        async let watches = api.fetchProjectWatches()
        homeClaudePending = await claude
        homeNotesApprovals = (await approvals)?.items ?? []
        uploadsQueue = await uploads
        projectWatches = await watches
        for watch in projectWatches.prefix(3) {
            guard let slug = watch.project_slug, !slug.isEmpty else { continue }
            if let summaryResp = await api.fetchProjectSummary(projectSlug: slug), summaryResp.success == true, let summary = summaryResp.summary {
                projectSummaries[slug] = summary
            }
        }
        taskBoardLoading = false
    }

    func createHomeTask() async {
        taskBoardLoading = true
        let title = taskTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let description = taskDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        let response = await api.createTask(
            title: title,
            description: description,
            taskType: taskType,
            priority: taskPriority
        )
        if response?.success == true {
            quickActionResult = "✅ Task created (#\(response?.task_id ?? 0))"
            taskTitle = ""
            taskDescription = ""
            await refreshHomeTaskBoard()
        } else {
            quickActionResult = response?.error ?? api.error ?? "Failed to create task"
        }
        taskBoardLoading = false
    }

    func approveHomeClaudeTask(_ task: ClaudeTask) async {
        taskBoardLoading = true
        let (success, message) = await api.approveClaudeTask(id: task.id)
        quickActionResult = success ? "✅ \(message)" : "❌ \(message)"
        await refreshHomeTaskBoard()
        taskBoardLoading = false
    }

    func approveHomeNoteTask(_ approvalID: String) async {
        taskBoardLoading = true
        let response = await api.approveNotesTaskApproval(approvalID: approvalID)
        if response?.success == true {
            quickActionResult = "✅ Note task approved"
        } else {
            quickActionResult = response?.error ?? api.error ?? "Failed to approve note task"
        }
        await refreshHomeTaskBoard()
        taskBoardLoading = false
    }

    func uploadTaskIntakeFile(_ fileURL: URL) async {
        taskBoardLoading = true
        let cleanProject = uploadProjectName.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanClient = uploadClientName.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanAddress = uploadAddressLine.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanLocation = uploadLocationName.trimmingCharacters(in: .whitespacesAndNewlines)
        let title = "Review \(uploadCategory): \(cleanProject.isEmpty ? (cleanClient.isEmpty ? fileURL.lastPathComponent : cleanClient) : cleanProject)"
        let response = await api.uploadTaskIntake(
            fileURL: fileURL,
            category: uploadCategory,
            projectName: cleanProject,
            clientName: cleanClient,
            addressLine: cleanAddress,
            locationName: cleanLocation,
            discipline: uploadDiscipline.trimmingCharacters(in: .whitespacesAndNewlines),
            sheetNumber: uploadSheetNumber.trimmingCharacters(in: .whitespacesAndNewlines),
            revision: uploadRevision.trimmingCharacters(in: .whitespacesAndNewlines),
            issueDate: uploadIssueDate.trimmingCharacters(in: .whitespacesAndNewlines),
            title: title,
            description: "Uploaded from SymphonyOps Home Task Board",
            priority: "high"
        )
        if response?.success == true {
            quickActionResult = "✅ Uploaded + task created (#\(response?.task_id ?? 0))\n\(response?.stored_filename ?? "")"
            await refreshHomeTaskBoard()
        } else {
            quickActionResult = "❌ Upload failed: \(response?.error ?? api.error ?? "Unknown error")"
        }
        taskBoardLoading = false
    }

    func uploadProjectBundleFile(_ fileURL: URL) async {
        taskBoardLoading = true
        guard fileURL.pathExtension.lowercased() == "zip" else {
            quickActionResult = "❌ Select a .zip file for project bundle upload."
            taskBoardLoading = false
            return
        }
        let cleanProject = uploadProjectName.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanClient = uploadClientName.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanAddress = uploadAddressLine.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanLocation = uploadLocationName.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanWatchPath = uploadWatchFolderPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let response = await api.uploadProjectBundle(
            fileURL: fileURL,
            projectName: cleanProject,
            clientName: cleanClient,
            addressLine: cleanAddress,
            locationName: cleanLocation,
            sourceFolderPath: cleanWatchPath,
            enableWatch: !cleanWatchPath.isEmpty,
            priority: "high"
        )
        if response?.success == true {
            let watchBadge = (response?.watch_registered ?? false) ? " • watch on" : ""
            quickActionResult = "✅ Project bundle queued (#\(response?.task_id ?? 0)) • files: \(response?.extracted_count ?? 0)\(watchBadge)"
            await refreshHomeTaskBoard()
        } else {
            quickActionResult = "❌ Bundle upload failed: \(response?.error ?? api.error ?? "Unknown error")"
        }
        taskBoardLoading = false
    }

    func runWatchScanNow() async {
        taskBoardLoading = true
        let response = await api.runProjectWatches()
        if response?.success == true {
            quickActionResult = "✅ Watch scan complete • processed \(response?.processed_total ?? 0) files"
            await refreshHomeTaskBoard()
        } else {
            quickActionResult = "❌ Watch scan failed: \(response?.error ?? api.error ?? "Unknown error")"
        }
        taskBoardLoading = false
    }

    func discoverProjectWatchesNow() async {
        taskBoardLoading = true
        let response = await api.discoverProjectWatches()
        if response?.success == true {
            quickActionResult = "✅ Discovery complete • new watches \(response?.registered ?? 0)"
            await refreshHomeTaskBoard()
        } else {
            quickActionResult = "❌ Watch discovery failed: \(response?.error ?? api.error ?? "Unknown error")"
        }
        taskBoardLoading = false
    }

    func statusColor(_ status: String) -> Color {
        switch status.lowercased() {
        case "complete":
            return .green
        case "closed":
            return .gray
        default:
            return .orange
        }
    }
}

// MARK: - AI Chat View

struct AIChatView: View {
    @EnvironmentObject var api: APIClient
    @State private var message = ""
    @State private var chatHistory: [ChatMessage] = []
    @State private var isLoading = false
    
    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                // AI Source indicator + Model Picker
                HStack {
                    Image(systemName: "brain.head.profile")
                        .foregroundColor(.orange)
                    Menu {
                        Button("Auto (smart routing)") { api.setPreferredAISource("auto") }
                        Button("Cortex (knowledge)") { api.setPreferredAISource("cortex") }
                        Button("Ollama (local)") { api.setPreferredAISource("ollama") }
                        Button("LM Studio (local)") { api.setPreferredAISource("lm_studio") }
                        Button("GPT-4o-mini") { api.setPreferredAISource("gpt-4o-mini") }
                        Button("Perplexity (research)") { api.setPreferredAISource("perplexity") }
                    } label: {
                        Text(aiSourceLabel(api.preferredAISource))
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                    Spacer()
                    if !chatHistory.isEmpty {
                        Button("Clear") {
                            chatHistory.removeAll()
                        }
                        .font(.caption)
                    }
                }
                .padding(.horizontal)
                .padding(.vertical, 8)
                .background(Color(.systemGray6))
                
                // Chat messages
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 12) {
                            ForEach(chatHistory) { msg in
                                ChatBubble(message: msg)
                                    .id(msg.id)
                            }
                            
                            if isLoading {
                                HStack {
                                    ProgressView()
                                        .scaleEffect(0.8)
                                    Text("Thinking...")
                                        .font(.caption)
                                        .foregroundColor(.secondary)
                                }
                                .padding()
                            }
                        }
                        .padding()
                    }
                    .onChange(of: chatHistory.count) { _ in
                        if let last = chatHistory.last {
                            withAnimation {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                }
                
                // Input
                HStack(spacing: 12) {
                    TextField("Ask Bob anything...", text: $message)
                        .textFieldStyle(RoundedBorderTextFieldStyle())
                        .disabled(isLoading)
                    
                    Button(action: sendMessage) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title)
                            .foregroundColor(message.isEmpty ? .gray : .orange)
                    }
                    .disabled(message.isEmpty || isLoading)
                }
                .padding()
                .background(Color(.systemBackground))
            }
            .navigationTitle("Ask Bob")
        }
    }
    
    func aiSourceLabel(_ source: String) -> String {
        switch source {
        case "auto": return "Auto"
        case "cortex": return "Cortex"
        case "ollama": return "Ollama"
        case "lm_studio": return "LM Studio"
        case "gpt-4o-mini": return "GPT-4o-mini"
        case "perplexity": return "Perplexity"
        default: return source
        }
    }
    
    func sendMessage() {
        let userMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !userMessage.isEmpty else { return }
        
        chatHistory.append(ChatMessage(role: "user", content: userMessage))
        message = ""
        isLoading = true
        
        Task {
            let reply = await api.askAI(question: userMessage)
            await MainActor.run {
                chatHistory.append(ChatMessage(
                    role: "assistant",
                    content: reply.answer ?? "Sorry, I couldn't process that request.",
                    source: reply.source,
                    projectHint: reply.projectHint,
                    projectContextUsed: reply.projectContextUsed,
                    projectFilesScanned: reply.projectFilesScanned
                ))
                isLoading = false
            }
        }
    }
}

struct ChatMessage: Identifiable {
    let id = UUID()
    let role: String
    let content: String
    var source: String = "cloud"
    var projectHint: String? = nil
    var projectContextUsed: Bool = false
    var projectFilesScanned: [String] = []
    let timestamp = Date()
}

struct ChatBubble: View {
    let message: ChatMessage
    @State private var showProjectSources = false
    
    var isUser: Bool { message.role == "user" }
    
    func sourceColor(_ source: String) -> Color {
        switch source {
        case "cortex": return .green
        case "ollama": return .green
        case "lm_studio": return .green
        case "gpt-4o-mini": return .orange
        case "perplexity": return .blue
        default: return .gray
        }
    }
    
    func sourceLabel(_ source: String) -> String {
        switch source {
        case "cortex": return "📚 Knowledge (free)"
        case "ollama": return "🦙 Ollama (free)"
        case "lm_studio": return "🖥️ LM Studio (free)"
        case "gpt-4o-mini": return "⚡ GPT-4 Mini ($)"
        case "perplexity": return "🔍 Research ($$)"
        default: return source
        }
    }
    
    var body: some View {
        HStack {
            if isUser { Spacer() }
            
            VStack(alignment: isUser ? .trailing : .leading, spacing: 4) {
                Text(message.content)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(isUser ? Color.orange : Color(.systemGray5))
                    .foregroundColor(isUser ? .white : .primary)
                    .cornerRadius(16)
                
                if !isUser {
                    HStack(spacing: 4) {
                        Circle()
                            .fill(sourceColor(message.source))
                            .frame(width: 6, height: 6)
                        Text(sourceLabel(message.source))
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }

                    if !message.projectFilesScanned.isEmpty {
                        DisclosureGroup(
                            isExpanded: $showProjectSources,
                            content: {
                                VStack(alignment: .leading, spacing: 4) {
                                    ForEach(message.projectFilesScanned, id: \.self) { path in
                                        HStack(alignment: .top, spacing: 6) {
                                            Image(systemName: "doc.text")
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                            Text(path)
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                        }
                                    }
                                }
                                .padding(.top, 2)
                            },
                            label: {
                                let hintSuffix = (message.projectHint?.isEmpty == false) ? " - \(message.projectHint ?? "")" : ""
                                Text(
                                    "Project Scope Sources (\(message.projectFilesScanned.count))" + hintSuffix
                                )
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            }
                        )
                        .padding(.top, 2)
                    } else if message.projectContextUsed {
                        Text("Project Scope Sources: context matched")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                }
            }
            
            if !isUser { Spacer() }
        }
    }
}

// MARK: - Leads View

struct LeadsView: View {
    @EnvironmentObject var api: APIClient
    @State private var isLoading = false
    @State private var result: String?
    @State private var outreachQueue: String?
    
    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Find New Leads")) {
                    LeadActionRow(title: "Scan Builders", icon: "hammer.fill", color: .blue) {
                        await runLeadScan("builders")
                    }
                    
                    LeadActionRow(title: "Scan Realtors", icon: "house.fill", color: .green) {
                        await runLeadScan("realtors")
                    }
                    
                    LeadActionRow(title: "Luxury Listings", icon: "building.2.fill", color: .purple) {
                        await runLeadScan("listings")
                    }
                    
                    LeadActionRow(title: "Property Managers", icon: "building.fill", color: .orange) {
                        await runLeadScan("property")
                    }
                }
                
                Section(header: Text("Outreach")) {
                    LeadActionRow(title: "View Outreach Queue", icon: "tray.full.fill", color: .indigo) {
                        await loadOutreachQueue()
                    }
                    
                    LeadActionRow(title: "Generate Drafts", icon: "envelope.fill", color: .cyan) {
                        await generateOutreach()
                    }
                }
                
                if isLoading {
                    HStack {
                        Spacer()
                        ProgressView("Scanning...")
                        Spacer()
                    }
                    .padding()
                }
                
                if let result = result {
                    Section(header: Text("Results")) {
                        ScrollView {
                            Text(result)
                                .font(.system(.caption, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .frame(maxHeight: 400)
                    }
                }
                
                if let queue = outreachQueue {
                    Section(header: Text("Outreach Queue")) {
                        Text(queue)
                            .font(.system(.caption, design: .monospaced))
                    }
                }
            }
            .navigationTitle("Leads")
            .refreshable {
                await loadOutreachQueue()
            }
        }
    }
    
    func runLeadScan(_ type: String) async {
        isLoading = true
        result = nil
        let scanResult = await api.runCommand("/leads/\(type)")
        result = scanResult?.output ?? scanResult?.error ?? "Scan failed"
        isLoading = false
    }
    
    func loadOutreachQueue() async {
        isLoading = true
        let queueResult = await api.runCommand("/leads/outreach/queue")
        outreachQueue = queueResult?.output ?? "No outreach queued"
        isLoading = false
    }
    
    func generateOutreach() async {
        isLoading = true
        let genResult = await api.runCommand("/leads/outreach/generate")
        result = genResult?.output ?? genResult?.error ?? "Generation failed"
        isLoading = false
    }
}

struct LeadActionRow: View {
    let title: String
    let icon: String
    let color: Color
    let action: () async -> Void
    
    var body: some View {
        Button(action: {
            Task { await action() }
        }) {
            HStack {
                Image(systemName: icon)
                    .foregroundColor(color)
                    .frame(width: 30)
                Text(title)
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundColor(.secondary)
            }
        }
        .foregroundColor(.primary)
    }
}

// MARK: - Usage View

struct UsageView: View {
    @EnvironmentObject var api: APIClient
    @State private var usageData: UsageData?
    @State private var isLoading = false
    
    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 20) {
                    if let usage = usageData {
                        // Total Cost Card
                        VStack(spacing: 8) {
                            Text("Monthly Spend")
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                            Text("$\(Int(usage.subscriptions.monthly_total))")
                                .font(.largeTitle)
                                .fontWeight(.bold)
                            Text("\(usage.subscriptions.count) services")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color(.systemGray6))
                        .cornerRadius(12)
                        .padding(.horizontal)
                        
                        // Service Usage Cards
                        ForEach(usage.services, id: \.service) { service in
                            UsageCard(service: service)
                        }
                    } else if isLoading {
                        ProgressView("Loading usage data...")
                            .padding()
                    } else {
                        Text("Pull to refresh")
                            .foregroundColor(.secondary)
                            .padding()
                    }
                }
                .padding(.vertical)
            }
            .navigationTitle("Usage Monitor")
            .refreshable {
                await fetchUsage()
            }
            .task {
                await fetchUsage()
            }
        }
    }
    
    func fetchUsage() async {
        isLoading = true
        usageData = await api.fetchUsage()
        isLoading = false
    }
}

struct UsageCard: View {
    let service: ServiceUsage
    
    var statusColor: Color {
        switch service.status {
        case "critical": return .red
        case "warning": return .yellow
        default: return .green
        }
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Circle()
                    .fill(statusColor)
                    .frame(width: 12, height: 12)
                Text(service.service)
                    .font(.headline)
                Spacer()
                Text("$\(Int(service.cost))/mo")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }
            
            // Progress bar
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle()
                        .fill(Color(.systemGray5))
                        .frame(height: 8)
                        .cornerRadius(4)
                    
                    Rectangle()
                        .fill(statusColor)
                        .frame(width: geo.size.width * CGFloat(service.pct) / 100, height: 8)
                        .cornerRadius(4)
                }
            }
            .frame(height: 8)
            
            HStack {
                Text("\(Int(service.pct))% used")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                if service.unit == "% Auto+Composer" {
                    Text("Auto: \(Int(service.used))%")
                        .font(.caption)
                        .foregroundColor(.secondary)
                } else if service.unit == "$" {
                    Text("$\(String(format: "%.2f", service.used)) / $\(Int(service.limit))")
                        .font(.caption)
                        .foregroundColor(.secondary)
                } else {
                    Text("\(Int(service.used)) / \(Int(service.limit)) \(service.unit)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            
            if let resetDate = service.reset_date {
                Text("Resets: \(resetDate)")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(12)
        .padding(.horizontal)
    }
}

// MARK: - Services View

struct ServicesView: View {
    @EnvironmentObject var api: APIClient
    
    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Running Services")) {
                    ForEach(api.services.filter { $0.isRunning }) { service in
                        ServiceRow(service: service)
                    }
                }
                
                Section(header: Text("Stopped Services")) {
                    ForEach(api.services.filter { !$0.isRunning }) { service in
                        ServiceRow(service: service)
                    }
                }
            }
            .navigationTitle("Services")
            .refreshable {
                await api.fetchServices()
            }
        }
    }
}

struct ServiceRow: View {
    let service: ServiceStatus
    
    var body: some View {
        HStack {
            Circle()
                .fill(service.isRunning ? Color.green : Color.red)
                .frame(width: 10, height: 10)
            
            VStack(alignment: .leading) {
                Text(service.name)
                    .font(.headline)
                
                if let port = service.port {
                    Text("Port \(port)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            
            Spacer()
            
            Text(service.status)
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }
}

// MARK: - Facts View (cortex ingest)

struct FactsView: View {
    @EnvironmentObject var api: APIClient
    @State private var pastedText = ""
    @State private var category = "control4"
    @State private var learnNow = false
    @State private var resultMessage: String?
    @State private var ingestLoading = false
    @State private var curatorLoading = false
    @State private var curatorStatus: CuratorStatusResponse?
    @State private var reviewItems: [CuratorQueueItem] = []
    @State private var selectedFactIDs: Set<Int> = []
    @State private var memoryGuard: MemoryGuardStatusResponse?
    @State private var showTrustedFacts = false
    @FocusState private var isTextFieldFocused: Bool
    
    private let categories = ["control4", "lutron", "audio", "video", "networking", "general"]
    
    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Paste facts to learn")) {
                    TextEditor(text: $pastedText)
                        .frame(minHeight: 120)
                        .font(.body)
                        .focused($isTextFieldFocused)
                    
                    Text("Paste C4 driver info, product specs, manuals, etc. Workers will learn it into the cortex.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                
                Section(header: Text("Category")) {
                    Picker("Category", selection: $category) {
                        ForEach(categories, id: \.self) { cat in
                            Text(cat.capitalized).tag(cat)
                        }
                    }
                    .pickerStyle(.menu)
                    
                    Toggle("Learn now (run one cycle)", isOn: $learnNow)
                }
                
                Section {
                    Button(action: submitFacts) {
                        HStack {
                            if ingestLoading {
                                ProgressView()
                            } else {
                                Image(systemName: "brain.head.profile")
                            }
                            Text("Learn into Cortex")
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                    }
                    .disabled(pastedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || ingestLoading)
                }
                
                Section(header: Text("Cortex Curator")) {
                    if let status = curatorStatus {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Facts: \(status.total_facts)")
                                    .font(.subheadline)
                                Text("Trusted \(status.trusted_facts) • Review \(status.review_facts) • Contradictions \(status.contradiction_pairs)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                            Spacer()
                            if curatorLoading {
                                ProgressView()
                            }
                        }
                    } else if curatorLoading {
                        ProgressView("Loading curator status…")
                    } else {
                        Text("Curator status unavailable")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }

                    if let guardStatus = memoryGuard?.job {
                        HStack(spacing: 8) {
                            Circle()
                                .fill(guardStatus.running ? Color.green : (guardStatus.loaded ? Color.orange : Color.red))
                                .frame(width: 8, height: 8)
                            Text("Memory Guard")
                                .font(.subheadline)
                            Spacer()
                            Text(guardStatus.running ? "Running" : (guardStatus.loaded ? "Loaded" : "Not loaded"))
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }

                    HStack {
                        Button("Run Curator") {
                            Task { await runCuratorNow() }
                        }
                        .disabled(curatorLoading)
                        Button("Refresh") {
                            Task { await loadCuratorData() }
                        }
                        .disabled(curatorLoading)
                        Spacer()
                        Toggle("Show trusted", isOn: $showTrustedFacts)
                            .labelsHidden()
                    }
                }

                Section(header: Text("Review Queue")) {
                    if reviewItems.isEmpty {
                        Text(curatorLoading ? "Loading…" : "No facts in current filter")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    } else {
                        ForEach(reviewItems) { item in
                            Button {
                                toggleSelection(item.id)
                            } label: {
                                CuratorFactRow(
                                    item: item,
                                    isSelected: selectedFactIDs.contains(item.id)
                                )
                            }
                            .buttonStyle(.plain)
                        }
                    }

                    HStack {
                        Button("Promote Selected") {
                            Task { await promoteSelectedFacts() }
                        }
                        .disabled(selectedFactIDs.isEmpty || curatorLoading)
                        Button("Demote Selected") {
                            Task { await demoteSelectedFacts() }
                        }
                        .disabled(selectedFactIDs.isEmpty || curatorLoading)
                    }
                }

                if let msg = resultMessage {
                    Section(header: Text("Result")) {
                        Text(msg)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .navigationTitle("Facts")
            .refreshable {
                await loadCuratorData()
            }
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { isTextFieldFocused = false }
                }
            }
            .task {
                await loadCuratorData()
            }
            .onChange(of: showTrustedFacts) { _ in
                Task { await loadCuratorReviewOnly() }
            }
        }
    }
    
    func submitFacts() {
        let text = pastedText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        
        ingestLoading = true
        resultMessage = nil
        
        Task {
            if let result = await api.submitFacts(text: text, category: category, learnNow: learnNow) {
                if result.success {
                    let path = result.path ?? "saved"
                    let chars = result.chars ?? 0
                    resultMessage = "Saved to \(path) (\(chars) chars)"
                    if result.learned == true {
                        resultMessage! += " • Learned"
                    }
                    pastedText = ""
                    await loadCuratorData()
                } else {
                    resultMessage = result.error ?? "Failed"
                }
            } else {
                resultMessage = api.error ?? "Connection failed"
            }
            ingestLoading = false
        }
    }

    func loadCuratorData() async {
        curatorLoading = true
        async let status = api.fetchCuratorStatus()
        async let review = api.fetchCuratorReview(status: showTrustedFacts ? "trusted" : "review")
        async let guardStatus = api.fetchMemoryGuardStatus()
        curatorStatus = await status
        reviewItems = await review?.items ?? []
        memoryGuard = await guardStatus
        selectedFactIDs = selectedFactIDs.intersection(Set(reviewItems.map(\.id)))
        curatorLoading = false
    }

    func loadCuratorReviewOnly() async {
        curatorLoading = true
        let review = await api.fetchCuratorReview(status: showTrustedFacts ? "trusted" : "review")
        reviewItems = review?.items ?? []
        selectedFactIDs.removeAll()
        curatorLoading = false
    }

    func runCuratorNow() async {
        curatorLoading = true
        let result = await api.runCurator(limit: 0, force: false)
        if let result {
            if result.success {
                resultMessage = "Curator updated: +\(result.new_facts ?? 0) new, \(result.updated_facts ?? 0) updated"
            } else {
                resultMessage = result.error ?? "Curator run failed"
            }
        } else {
            resultMessage = api.error ?? "Curator run failed"
        }
        await loadCuratorData()
    }

    func promoteSelectedFacts() async {
        curatorLoading = true
        let ids = Array(selectedFactIDs).sorted()
        let response = await api.promoteCuratorFacts(ids: ids)
        if response?.success == true {
            resultMessage = "Promoted \(response?.updated ?? 0) fact(s) to trusted"
            selectedFactIDs.removeAll()
        } else {
            resultMessage = response?.error ?? api.error ?? "Promote failed"
        }
        await loadCuratorData()
    }

    func demoteSelectedFacts() async {
        curatorLoading = true
        let ids = Array(selectedFactIDs).sorted()
        let response = await api.demoteCuratorFacts(ids: ids)
        if response?.success == true {
            resultMessage = "Demoted \(response?.updated ?? 0) fact(s) to review"
            selectedFactIDs.removeAll()
        } else {
            resultMessage = response?.error ?? api.error ?? "Demote failed"
        }
        await loadCuratorData()
    }

    func toggleSelection(_ id: Int) {
        if selectedFactIDs.contains(id) {
            selectedFactIDs.remove(id)
        } else {
            selectedFactIDs.insert(id)
        }
    }
}

struct CuratorFactRow: View {
    let item: CuratorQueueItem
    let isSelected: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundColor(isSelected ? .orange : .secondary)
                Text(item.fact)
                    .font(.subheadline)
                    .foregroundColor(.primary)
                    .lineLimit(3)
                Spacer()
                Text(String(format: "%.2f", item.confidence))
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            HStack(spacing: 10) {
                Text("src \(item.source_count)")
                Text("contra \(item.contradictions)")
                Text("dom \(String(format: "%.2f", item.domain_score))")
                Text("reas \(String(format: "%.2f", item.reasoning_score))")
                Text("diag \(String(format: "%.2f", item.troubleshooting_score))")
            }
            .font(.caption2)
            .foregroundColor(.secondary)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Actions View

struct ActionsView: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var searchQuery = ""
    @State private var result: String?
    @State private var isLoading = false
    @State private var showProductImporter = false
    @State private var selectedSheetURL: URL?
    @State private var dealerTier = "standard"
    @State private var maxProducts = 25
    @State private var createInDTools = false
    @State private var dryRun = true
    @State private var productImportResponse: DToolsProductImportResponse?
    @State private var parseProfile = "msrp_three_tiers"
    @State private var customExpectedColumns = "MODEL NAME, PART NUMBER, SKU, DESCRIPTION, MSRP, STANDARD DEALER, SILVER DEALER, GOLD DEALER"
    @State private var shouldScrollToProductResult = false
    @State private var approveStoreResult: DToolsProductStoreResponse?
    @State private var retryCreateResult: DToolsProductRetryResponse?
    @State private var dtoolsAuthStatus: DToolsAuthCheckResponse?
    @State private var editableProducts: [EditableProductDraft] = []
    @State private var manualDigestProjectName = ""
    @State private var manualDigestRunAI = true
    @State private var showManualDigestImporter = false
    @State private var selectedManualDigestFiles: [URL] = []
    @State private var manualDigestResponse: ProjectManualDigestResponse?
    @State private var proposalScopeProjectName = ""
    @State private var proposalScopeClientName = ""
    @State private var proposalScopeRunAI = true
    @State private var showProposalScopeImporter = false
    @State private var selectedProposalScopeFile: URL?
    @State private var proposalScopeResponse: ProposalScopeResponse?
    @State private var notesProcessTarget = ""
    @State private var notesPipelineStatus: NotesPipelineStatusResponse?
    @State private var opsHealth: OpsHealthResponse?
    @State private var incidentQueue: IncidentQueueResponse?
    @State private var contactsStatus: ContactsStatusResponse?
    @State private var contactsList: [ContactListItem] = []
    @State private var contactsSearch = ""
    @State private var selectedContactIDs: Set<String> = []
    @State private var iMessageWatchlist: [String] = []
    @State private var recentWorkTexts: [IMessageRecentItem] = []
    @State private var isRefreshingRecentWorkTexts = false
    @State private var newClientName = ""
    @State private var newClientPhone = ""
    @State private var newClientEmail = ""
    @State private var notesProjectLinkRules: [NotesProjectLinkRule] = []
    @State private var notesTaskApprovals: [NotesTaskApprovalItem] = []
    @State private var noteLinkMatchText = ""
    @State private var noteLinkProjectName = ""
    @State private var shareTemplateFileURL: URL?
    @State private var showTemplateShareSheet = false
    @State private var exportFileURL: URL?
    @State private var showExportShareSheet = false
    @State private var didInitialActionsLoad = false
    private let perfLogger = Logger(subsystem: "com.symphonysh.SymphonyOps", category: "perf")

    enum ActionWorkspace: String, CaseIterable, Identifiable {
        case dailyOps = "Daily Ops"
        case projects = "Projects"
        case growth = "Growth"
        case aiTools = "AI Tools"

        var id: String { rawValue }
    }
    @State private var actionWorkspace: ActionWorkspace = .dailyOps
    
    var markupURL: URL {
        api.markupURL ?? api.fallbackMarkupURL
    }

    private func opsStatusLabel(_ status: String) -> String {
        switch status.lowercased() {
        case "healthy":
            return "On Track"
        case "degraded":
            return "Needs Attention"
        default:
            return status.capitalized
        }
    }

    private func opsStatusColor(_ status: String) -> Color {
        status.lowercased() == "healthy" ? .green : .orange
    }

    @ViewBuilder
    private var projectsWorkspaceSections: some View {
        Section(header: Text("Symphony Markup")) {
            Link(destination: markupURL) {
                HStack {
                    Image(systemName: "pencil.and.outline")
                        .font(.title2)
                        .foregroundColor(.orange)
                        .frame(width: 40)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Open Markup Tool")
                            .font(.headline)
                        Text("Floor plans, symbols, D-Tools export")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        Text("Saves to iCloud + Bob • Add to Home Screen")
                            .font(.caption2)
                            .foregroundColor(.green)
                    }
                    Spacer()
                    Image(systemName: "safari")
                        .foregroundColor(.blue)
                }
                .padding(.vertical, 8)
            }
            .foregroundColor(.primary)
        }

        Section(header: Text("D-Tools Product Agent")) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Upload a price/data sheet, parse products, and optionally create products in d-tools.cloud.")
                    .font(.caption)
                    .foregroundColor(.secondary)

                Button {
                    if !showProductImporter {
                        showProductImporter = true
                    }
                } label: {
                    HStack {
                        Image(systemName: "doc.badge.plus")
                        Text(selectedSheetURL == nil ? "Choose PDF/CSV Sheet" : selectedSheetURL!.lastPathComponent)
                            .lineLimit(1)
                    }
                }
                .buttonStyle(.bordered)
                .fileImporter(
                    isPresented: $showProductImporter,
                    allowedContentTypes: [.pdf, .commaSeparatedText, .plainText, .data],
                    allowsMultipleSelection: false
                ) { result in
                    showProductImporter = false
                    switch result {
                    case .success(let urls):
                        selectedSheetURL = urls.first
                    case .failure(let err):
                        self.result = "File picker failed: \(err.localizedDescription)"
                    }
                }

                Picker("Dealer Tier", selection: $dealerTier) {
                    Text("Standard").tag("standard")
                    Text("Silver").tag("silver")
                    Text("Gold").tag("gold")
                    Text("Fabricator").tag("fabricator")
                }
                .pickerStyle(.menu)

                Picker("Document Profile", selection: $parseProfile) {
                    Text("Auto Detect").tag("auto")
                    Text("MSRP + Standard/Silver/Gold").tag("msrp_three_tiers")
                    Text("MSRP + Standard only").tag("msrp_standard_only")
                    Text("Minimal").tag("minimal")
                    Text("Custom Columns").tag("custom")
                }
                .pickerStyle(.menu)

                if parseProfile == "custom" {
                    TextField(
                        "Comma-separated columns",
                        text: $customExpectedColumns,
                        axis: .vertical
                    )
                    .lineLimit(2...4)
                    .textInputAutocapitalization(.characters)
                    .font(.caption)
                }

                Stepper("Max Products: \(maxProducts)", value: $maxProducts, in: 1...250)

                Toggle("Create in D-Tools", isOn: $createInDTools)
                Toggle("Dry Run", isOn: $dryRun)
                    .onChange(of: dryRun) { newValue in
                        if !newValue { createInDTools = true }
                    }
                    .onChange(of: createInDTools) { newValue in
                        if !newValue { dryRun = true }
                    }

                Button {
                    Task { await runDToolsAuthCheck() }
                } label: {
                    HStack {
                        Image(systemName: "checkmark.shield")
                        Text("Check D-Tools Product Auth")
                    }
                }
                .buttonStyle(.bordered)
                .disabled(isLoading)

                if let auth = dtoolsAuthStatus {
                    Text((auth.success ? "✅ " : "❌ ") + (auth.message ?? auth.error ?? "Auth check complete"))
                        .font(.caption2)
                        .foregroundColor(auth.success ? .green : .orange)
                }

                Button {
                    Task { await runProductImport() }
                } label: {
                    HStack {
                        Image(systemName: "wand.and.stars")
                        Text("Run Product Agent")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading || selectedSheetURL == nil)
            }
        }

        Section(header: Text("New Project Manual Digest")) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Upload manuals, notes, and docs for a new project. The agent extracts recommended devices, scope clues, risks, and questions.")
                    .font(.caption)
                    .foregroundColor(.secondary)

                if let intakeURL = api.manualDigestIntakeTemplateURL {
                    HStack(spacing: 8) {
                        Link(destination: intakeURL) {
                            HStack {
                                Image(systemName: "square.and.arrow.down")
                                Text("Download Intake PDF")
                            }
                        }
                        .buttonStyle(.bordered)

                        Button {
                            Task { await shareIntakeTemplate() }
                        } label: {
                            HStack {
                                Image(systemName: "square.and.arrow.up")
                                Text("Share Intake PDF")
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isLoading)
                    }
                }

                TextField("Project name (e.g. Wildridge Residence)", text: $manualDigestProjectName)
                    .textFieldStyle(.roundedBorder)

                Button {
                    if !showManualDigestImporter {
                        showManualDigestImporter = true
                    }
                } label: {
                    HStack {
                        Image(systemName: "doc.on.doc.fill")
                        Text(selectedManualDigestFiles.isEmpty ? "Choose Project Files" : "\(selectedManualDigestFiles.count) file(s) selected")
                    }
                }
                .buttonStyle(.bordered)
                .fileImporter(
                    isPresented: $showManualDigestImporter,
                    allowedContentTypes: [.pdf, .plainText, .commaSeparatedText, .data],
                    allowsMultipleSelection: true
                ) { result in
                    showManualDigestImporter = false
                    switch result {
                    case .success(let urls):
                        selectedManualDigestFiles = urls
                    case .failure(let err):
                        self.result = "Manual Digest picker failed: \(err.localizedDescription)"
                    }
                }

                Toggle("Run AI summary", isOn: $manualDigestRunAI)

                Button {
                    Task { await runManualDigest() }
                } label: {
                    HStack {
                        Image(systemName: "brain.head.profile")
                        Text("Run Manual Digest Agent")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading || selectedManualDigestFiles.isEmpty)
            }
        }

        Section(header: Text("Proposal Scope Agent")) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Upload a finished proposal and get a structured scope of work, inclusions, exclusions, assumptions, and risks.")
                    .font(.caption)
                    .foregroundColor(.secondary)

                TextField("Project name", text: $proposalScopeProjectName)
                    .textFieldStyle(.roundedBorder)
                TextField("Client name", text: $proposalScopeClientName)
                    .textFieldStyle(.roundedBorder)

                Button {
                    if !showProposalScopeImporter {
                        showProposalScopeImporter = true
                    }
                } label: {
                    HStack {
                        Image(systemName: "doc.text.magnifyingglass")
                        Text(selectedProposalScopeFile == nil ? "Choose Finished Proposal" : selectedProposalScopeFile!.lastPathComponent)
                            .lineLimit(1)
                    }
                }
                .buttonStyle(.bordered)
                .fileImporter(
                    isPresented: $showProposalScopeImporter,
                    allowedContentTypes: [.pdf, .plainText, .commaSeparatedText, .data],
                    allowsMultipleSelection: false
                ) { result in
                    showProposalScopeImporter = false
                    switch result {
                    case .success(let urls):
                        selectedProposalScopeFile = urls.first
                    case .failure(let err):
                        self.result = "Proposal Scope picker failed: \(err.localizedDescription)"
                    }
                }

                Toggle("Run AI summary", isOn: $proposalScopeRunAI)

                Button {
                    Task { await runProposalScopeAgent() }
                } label: {
                    HStack {
                        Image(systemName: "doc.badge.gearshape")
                        Text("Run Proposal Scope Agent")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading || selectedProposalScopeFile == nil)
            }
        }
    }

    @ViewBuilder
    private var dailyOpsWorkspaceSections: some View {
        Section(header: Text("Automation Health")) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Unified ops status + one-tap autonomous recovery.")
                    .font(.caption)
                    .foregroundColor(.secondary)

                HStack {
                    Button {
                        Task { await runOpsRecoveryNow() }
                    } label: {
                        Label("Run Recovery Now", systemImage: "cross.case.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading)

                    Button {
                        Task { await refreshOpsHealth() }
                    } label: {
                        Label("Refresh Ops", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                }

                if let health = opsHealth {
                    Text("Ops: \(opsStatusLabel(health.status))")
                        .font(.caption2)
                        .foregroundColor(opsStatusColor(health.status))
                }
                if let queue = incidentQueue {
                    Text("Incident Queue: \(queue.count)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }
        }

        Section(header: Text("Notes Automation")) {
            VStack(alignment: .leading, spacing: 8) {
                TextField("Note ID (optional) or project hint", text: $notesProcessTarget)
                    .textFieldStyle(.roundedBorder)
                HStack {
                    Button {
                        Task { await processNotesNow() }
                    } label: {
                        Label("Process Note Now", systemImage: "bolt.horizontal.circle")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading)

                    Button {
                        Task { await refreshNotesPipelineStatus() }
                    } label: {
                        Label("Refresh Status", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                }
            }
        }

        Section(header: Text("Contacts + iMessages")) {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Button {
                        Task { await syncContactsAndRefresh() }
                    } label: {
                        Label("Sync Contacts", systemImage: "person.2.badge.gearshape")
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)

                    Button {
                        Task { await processIMessagesNow() }
                    } label: {
                        Label("Process Texts Now", systemImage: "bolt.badge.clock")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading)
                }

                TextField("Search contacts by name/phone/email", text: $contactsSearch)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        Task { await refreshContactsList() }
                    }

                if !contactsList.isEmpty {
                    ForEach(contactsList.prefix(6)) { contact in
                        Text(contact.name)
                            .font(.caption2)
                    }
                }
            }
        }

        Section(header: Text("Project Note Linking + Approval")) {
            VStack(alignment: .leading, spacing: 8) {
                TextField("Match text (e.g. mitchell)", text: $noteLinkMatchText)
                    .textFieldStyle(.roundedBorder)
                TextField("Project name (e.g. Mitchell Residence)", text: $noteLinkProjectName)
                    .textFieldStyle(.roundedBorder)

                Button {
                    Task { await refreshNotesTaskApprovalPanel() }
                } label: {
                    Label("Refresh Queue", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
                .disabled(isLoading)

                Text("Pending Approvals: \(notesTaskApprovals.count)")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
    }
    
    var body: some View {
        NavigationView {
            ScrollViewReader { proxy in
                List {
                Section(header: Text("Focus Area")) {
                    Picker("Workspace", selection: $actionWorkspace) {
                        ForEach(ActionWorkspace.allCases) { workspace in
                            Text(workspace.rawValue).tag(workspace)
                        }
                    }
                    .pickerStyle(.segmented)
                    Text("Pick one focus area to reduce noise and keep priority tasks visible.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }

                if actionWorkspace == .projects {
                    projectsWorkspaceSections
                }

                if actionWorkspace == .dailyOps {
                    dailyOpsWorkspaceSections
                }

                if actionWorkspace == .projects {
                if let digest = manualDigestResponse {
                    Section(header: Text("Manual Digest Result")) {
                        Text("Project: \(digest.project_name ?? manualDigestProjectName)")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                        if let files = digest.files {
                            Text("Files processed: \(files.count)")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        if let brands = digest.digest?.detected_brands, !brands.isEmpty {
                            Text("Detected brands: \(brands.joined(separator: ", "))")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        if let skus = digest.digest?.detected_skus, !skus.isEmpty {
                            Text("Detected SKUs: \(skus.prefix(12).joined(separator: ", "))")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        if let rec = digest.ai_summary?.recommended_devices, !rec.isEmpty {
                            Text("Recommended devices:")
                                .font(.caption)
                                .fontWeight(.semibold)
                            ForEach(Array(rec.prefix(8).enumerated()), id: \.offset) { _, line in
                                Text("• \(line)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                        } else if let recNotes = digest.digest?.recommended_notes, !recNotes.isEmpty {
                            Text("Recommended notes:")
                                .font(.caption)
                                .fontWeight(.semibold)
                            ForEach(Array(recNotes.prefix(8).enumerated()), id: \.offset) { _, line in
                                Text("• \(line)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                        }
                        if let next = digest.ai_summary?.next_steps, !next.isEmpty {
                            Text("Next steps:")
                                .font(.caption)
                                .fontWeight(.semibold)
                            ForEach(Array(next.prefix(6).enumerated()), id: \.offset) { _, line in
                                Text("• \(line)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                        }
                    }
                    .id("manual-digest-result")
                }

                if let proposalScope = proposalScopeResponse {
                    Section(header: Text("Proposal Scope Result")) {
                        Text("Project: \(proposalScope.project_name ?? proposalScopeProjectName)")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                        if let quote = proposalScope.dtools_quote_version, !quote.isEmpty {
                            Text("D-Tools: \(quote)")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        if let scope = proposalScope.scope {
                            if let lines = scope.scope_of_work, !lines.isEmpty {
                                Text("Scope of work")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                ForEach(Array(lines.prefix(8).enumerated()), id: \.offset) { _, line in
                                    Text("• \(line)")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                            if let included = scope.included_items, !included.isEmpty {
                                Text("Included")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                ForEach(Array(included.prefix(8).enumerated()), id: \.offset) { _, line in
                                    Text("• \(line)")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                            if let excluded = scope.excluded_items, !excluded.isEmpty {
                                Text("Excluded")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                ForEach(Array(excluded.prefix(6).enumerated()), id: \.offset) { _, line in
                                    Text("• \(line)")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                            if let risks = scope.risk_tags, !risks.isEmpty {
                                Text("Risk tags: \(risks.joined(separator: ", "))")
                                    .font(.caption2)
                                    .foregroundColor(.orange)
                            }
                        }
                        if let next = proposalScope.ai_summary?.next_steps, !next.isEmpty {
                            Text("Next steps")
                                .font(.caption)
                                .fontWeight(.semibold)
                            ForEach(Array(next.prefix(6).enumerated()), id: \.offset) { _, line in
                                Text("• \(line)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                        }
                    }
                }

                if let importResponse = productImportResponse {
                    Section(header: Text("Product Agent Result")) {
                        Text("Parsed: \(importResponse.parsed_count ?? 0) • Attempted: \(importResponse.attempted_count ?? 0) • Created: \(importResponse.created_count ?? 0)")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        if let profile = importResponse.parse_profile {
                            Text("Profile: \(profile)")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        if let expectedColumns = importResponse.expected_columns, !expectedColumns.isEmpty {
                            Text("Columns: \(expectedColumns.joined(separator: ", "))")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }

                        if let error = importResponse.error, !error.isEmpty {
                            Text(error)
                                .font(.caption)
                                .foregroundColor(.red)
                        }

                        if !editableProducts.isEmpty {
                            HStack {
                                Button("Select All") {
                                    for idx in editableProducts.indices {
                                        editableProducts[idx].isSelected = true
                                    }
                                }
                                Button("Clear") {
                                    for idx in editableProducts.indices {
                                        editableProducts[idx].isSelected = false
                                    }
                                }
                            }
                            .font(.caption)

                            ForEach($editableProducts) { $product in
                                VStack(alignment: .leading, spacing: 6) {
                                    Toggle(isOn: $product.isSelected) {
                                        Text(product.model.isEmpty ? "Unnamed Product" : product.model)
                                            .font(.subheadline)
                                            .fontWeight(.semibold)
                                    }

                                    TextField("Brand", text: $product.brand)
                                        .textFieldStyle(.roundedBorder)
                                    TextField("Model", text: $product.model)
                                        .textFieldStyle(.roundedBorder)
                                    TextField("Part Number", text: $product.partNumber)
                                        .textFieldStyle(.roundedBorder)
                                    TextField("Category", text: $product.category)
                                        .textFieldStyle(.roundedBorder)
                                    TextField("Short Description", text: $product.shortDescription, axis: .vertical)
                                        .lineLimit(2...4)
                                        .textFieldStyle(.roundedBorder)
                                    TextField("Supplier", text: $product.supplier)
                                        .textFieldStyle(.roundedBorder)

                                    HStack {
                                        TextField("Unit Price", text: $product.unitPrice)
                                            .textFieldStyle(.roundedBorder)
                                            .keyboardType(.decimalPad)
                                        TextField("Unit Cost", text: $product.unitCost)
                                            .textFieldStyle(.roundedBorder)
                                            .keyboardType(.decimalPad)
                                        TextField("MSRP", text: $product.msrp)
                                            .textFieldStyle(.roundedBorder)
                                            .keyboardType(.decimalPad)
                                    }
                                }
                                .padding(.vertical, 4)
                            }

                            Button {
                                Task {
                                    await retryCreateSelectedProducts(importResponse)
                                }
                            } label: {
                                HStack {
                                    Image(systemName: "arrow.clockwise.circle.fill")
                                    Text("Retry Create Selected in D-Tools")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading || selectedDraftProducts().isEmpty)

                            Button {
                                Task {
                                    await approveAndStoreSelectedProducts(importResponse)
                                }
                            } label: {
                                HStack {
                                    Image(systemName: "checkmark.seal.fill")
                                    Text("Approve + Save Selected to Product DB")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(isLoading || selectedDraftProducts().isEmpty)

                            HStack {
                                Button {
                                    Task { await exportSelectedProducts(format: "csv") }
                                } label: {
                                    HStack {
                                        Image(systemName: "square.and.arrow.up")
                                        Text("Export Selected CSV")
                                    }
                                }
                                .buttonStyle(.bordered)
                                .disabled(isLoading || selectedDraftProducts().isEmpty)

                                Button {
                                    Task { await exportSelectedProducts(format: "json") }
                                } label: {
                                    HStack {
                                        Image(systemName: "doc.badge.gearshape")
                                        Text("Export Selected JSON")
                                    }
                                }
                                .buttonStyle(.bordered)
                                .disabled(isLoading || selectedDraftProducts().isEmpty)
                            }
                        }

                        if let store = approveStoreResult {
                            if store.success {
                                Text(
                                    "Saved \(store.saved_count ?? 0) • New \(store.inserted_count ?? 0) • Updated \(store.updated_count ?? 0) • Batch \(store.batch_id ?? 0)"
                                )
                                .font(.caption)
                                .foregroundColor(.green)
                            } else if let err = store.error {
                                Text(err)
                                    .font(.caption)
                                    .foregroundColor(.red)
                            }
                        }
                        if let retry = retryCreateResult {
                            if retry.success {
                                Text("Retry create: \(retry.created_count ?? 0) created, \(retry.failed_count ?? 0) failed")
                                    .font(.caption)
                                    .foregroundColor(.green)
                            } else if let err = retry.error {
                                Text(err)
                                    .font(.caption)
                                    .foregroundColor(.red)
                            }
                        }
                    }
                    .id("dtools-product-result")
                }
                }
                
                if actionWorkspace == .dailyOps || actionWorkspace == .aiTools {
                Section(header: Text("Search Knowledge")) {
                    HStack {
                        TextField("Search query...", text: $searchQuery)
                        
                        Button(action: {
                            Task {
                                isLoading = true
                                if let res = await api.search(query: searchQuery) {
                                    result = res.output ?? res.error
                                }
                                isLoading = false
                            }
                        }) {
                            if isLoading {
                                ProgressView()
                            } else {
                                Image(systemName: "magnifyingglass")
                            }
                        }
                        .disabled(searchQuery.isEmpty || isLoading)
                    }
                }
                }
                
                if (actionWorkspace == .dailyOps || actionWorkspace == .aiTools), let result = result {
                    Section(header: Text("Result")) {
                        ScrollView {
                            Text(result)
                                .font(.system(.caption, design: .monospaced))
                        }
                        .frame(maxHeight: 300)
                    }
                }
                
                if actionWorkspace == .growth {
                Section(header: Text("Social / X (@symphonysmart)")) {
                    ActionRow(title: "Story Tweet", icon: "book.fill") {
                        Task { isLoading = true; let r = await api.socialStory(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "Tip Tweet", icon: "lightbulb.fill") {
                        Task { isLoading = true; let r = await api.socialTip(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "Video Prompt", icon: "video.fill") {
                        Task { isLoading = true; let r = await api.socialVideo(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "Full Week", icon: "calendar") {
                        Task { isLoading = true; let r = await api.socialWeek(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "X Queue", icon: "list.bullet") {
                        Task { isLoading = true; let r = await api.socialXQueue(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "Post Next", icon: "paperplane.fill") {
                        Task { isLoading = true; let r = await api.socialXPost(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "X Usage", icon: "chart.bar") {
                        Task { isLoading = true; let r = await api.socialXUsage(); result = r?.output ?? r?.error; isLoading = false }
                    }
                }
                
                Section(header: Text("SEO")) {
                    ActionRow(title: "Keywords", icon: "key.fill") {
                        Task { isLoading = true; let r = await api.seoKeywords(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "Content Ideas", icon: "doc.text.fill") {
                        Task { isLoading = true; let r = await api.seoContent(); result = r?.output ?? r?.error; isLoading = false }
                    }
                    ActionRow(title: "Local Audit", icon: "mappin.circle.fill") {
                        Task { isLoading = true; let r = await api.seoLocal(); result = r?.output ?? r?.error; isLoading = false }
                    }
                }
                }
                
                if actionWorkspace == .dailyOps || actionWorkspace == .aiTools {
                Section(header: Text("Quick Commands")) {
                    ActionRow(title: "Fix Trading API (:8421)", icon: "bolt.horizontal.circle.fill") {
                        Task {
                            isLoading = true
                            let r = await api.fixTradingAPI()
                            if let output = r?.output, !output.isEmpty {
                                result = output
                            } else if let err = r?.error, !err.isEmpty {
                                result = err
                            } else if r?.success == true {
                                result = "Trading API watchdog completed."
                            } else {
                                result = "Trading API watchdog failed."
                            }
                            isLoading = false
                        }
                    }

                    ActionRow(title: "Morning Checklist", icon: "sunrise") {
                        Task {
                            isLoading = true
                            if let res = await api.runMorningChecklist() {
                                result = res.output ?? res.error
                            }
                            isLoading = false
                        }
                    }
                    
                    ActionRow(title: "Check Bids", icon: "hammer") {
                        Task {
                            isLoading = true
                            if let res = await api.checkBids() {
                                result = res.output ?? res.error
                            }
                            isLoading = false
                        }
                    }
                    
                    ActionRow(title: "List Bids", icon: "list.bullet") {
                        Task {
                            isLoading = true
                            if let res = await api.listBids() {
                                result = res.output ?? res.error
                            }
                            isLoading = false
                        }
                    }
                    
                    ActionRow(title: "Check Website", icon: "globe") {
                        Task {
                            isLoading = true
                            if await api.checkWebsite() != nil {
                                result = "Website check complete"
                            }
                            isLoading = false
                        }
                    }
                }
                }
            }
            .navigationTitle("Work Center")
            .onChange(of: shouldScrollToProductResult) { shouldScroll in
                guard shouldScroll else { return }
                withAnimation {
                    proxy.scrollTo("dtools-product-result", anchor: .top)
                }
                shouldScrollToProductResult = false
            }
        }
        }
        .task {
            guard !didInitialActionsLoad else { return }
            didInitialActionsLoad = true
            let loadStart = Date()
            async let markupTask: Void = api.fetchMarkupURL()
            async let notesPipelineTask: Void = refreshNotesPipelineStatus()
            async let opsTask: Void = refreshOpsHealth()
            async let incidentsTask: Void = refreshIncidentQueue()
            async let contactsTask: Void = refreshContactsPanel()
            async let approvalsTask: Void = refreshNotesTaskApprovalPanel()
            _ = await (markupTask, notesPipelineTask, opsTask, incidentsTask, contactsTask, approvalsTask)
            perfLogger.info("actions.initialLoad.ms=\(Int(Date().timeIntervalSince(loadStart) * 1000))")
        }
        .task {
            // Lightweight live feed polling while Actions view is visible.
            while !Task.isCancelled {
                if scenePhase == .active && actionWorkspace == .dailyOps {
                    await refreshRecentWorkTexts()
                }
                try? await Task.sleep(nanoseconds: 45_000_000_000)
            }
        }
        .sheet(isPresented: $showTemplateShareSheet) {
            if let fileURL = shareTemplateFileURL {
                ActivityView(activityItems: [fileURL])
            } else {
                Text("No file available to share.")
                    .padding()
            }
        }
        .sheet(isPresented: $showExportShareSheet) {
            if let fileURL = exportFileURL {
                ActivityView(activityItems: [fileURL])
            } else {
                Text("No export file available.")
                    .padding()
            }
        }
    }

    func runProductImport() async {
        guard let sheetURL = selectedSheetURL else { return }
        // Safety: ensure run action never reopens file picker.
        showProductImporter = false
        isLoading = true
        defer { isLoading = false }

        let response = await api.importDToolsProducts(
            fileURL: sheetURL,
            createInDTools: createInDTools,
            maxProducts: maxProducts,
            dealerTier: dealerTier,
            parseProfile: parseProfile == "custom" ? "auto" : parseProfile,
            expectedColumns: parseProfile == "custom" ? parseExpectedColumns(customExpectedColumns) : [],
            dryRun: dryRun
        )
        productImportResponse = response
        approveStoreResult = nil
        retryCreateResult = nil
        if let drafts = response?.products {
            editableProducts = drafts.map(EditableProductDraft.init)
        } else {
            editableProducts = []
        }
        if response == nil {
            result = api.error ?? "Product import failed"
        } else if response?.success == false {
            result = response?.error ?? "Product import failed"
        } else {
            result = "Product agent completed."
        }
        shouldScrollToProductResult = true
    }

    func runDToolsAuthCheck() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.checkDToolsProductAuth()
        dtoolsAuthStatus = response
        if response == nil {
            result = api.error ?? "Auth check failed"
        } else if response?.success == true {
            result = "D-Tools browser auth is healthy."
        } else {
            result = response?.message ?? response?.error ?? "D-Tools auth failed"
        }
    }

    func runManualDigest() async {
        guard !selectedManualDigestFiles.isEmpty else { return }
        isLoading = true
        defer { isLoading = false }
        let response = await api.runProjectManualDigest(
            projectName: manualDigestProjectName.trimmingCharacters(in: .whitespacesAndNewlines),
            fileURLs: selectedManualDigestFiles,
            runAISummary: manualDigestRunAI
        )
        manualDigestResponse = response
        if response == nil {
            result = api.error ?? "Manual digest failed"
        } else if response?.success == false {
            result = response?.error ?? "Manual digest failed"
        } else {
            result = "Manual digest completed."
        }
    }

    func runProposalScopeAgent() async {
        guard let proposalFile = selectedProposalScopeFile else { return }
        isLoading = true
        defer { isLoading = false }
        let response = await api.runProposalScopeAgent(
            projectName: proposalScopeProjectName.trimmingCharacters(in: .whitespacesAndNewlines),
            clientName: proposalScopeClientName.trimmingCharacters(in: .whitespacesAndNewlines),
            fileURL: proposalFile,
            runAISummary: proposalScopeRunAI
        )
        proposalScopeResponse = response
        if response == nil {
            result = api.error ?? "Proposal scope agent failed"
        } else if response?.success == false {
            result = response?.error ?? "Proposal scope agent failed"
        } else {
            result = "Proposal scope agent completed."
        }
    }

    func formatMoney(_ value: Double?) -> String {
        guard let value else { return "—" }
        return "$\(String(format: "%.2f", value))"
    }

    func parseExpectedColumns(_ raw: String) -> [String] {
        raw
            .split(separator: ",")
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    func selectedDraftProducts() -> [DToolsProductDraft] {
        editableProducts
            .filter { $0.isSelected && !$0.model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            .map { $0.toDraft() }
    }

    func approveAndStoreSelectedProducts(_ importResponse: DToolsProductImportResponse) async {
        isLoading = true
        defer { isLoading = false }
        let products = selectedDraftProducts()
        guard !products.isEmpty else { return }
        let response = await api.approveAndStoreDToolsProducts(
            products: products,
            sourceFile: importResponse.file,
            parseProfile: importResponse.parse_profile,
            dealerTier: importResponse.dealer_tier
        )
        approveStoreResult = response
        if response == nil {
            result = api.error ?? "Approve/store failed"
        } else if response?.success == false {
            result = response?.error ?? "Approve/store failed"
        } else {
            result = "Approved and saved to product DB."
        }
    }

    func retryCreateSelectedProducts(_ importResponse: DToolsProductImportResponse) async {
        isLoading = true
        defer { isLoading = false }
        let products = selectedDraftProducts()
        guard !products.isEmpty else { return }
        let response = await api.retryCreateDToolsProducts(
            products: products,
            sourceFile: importResponse.file,
            parseProfile: importResponse.parse_profile,
            dealerTier: importResponse.dealer_tier
        )
        retryCreateResult = response
        if response == nil {
            result = api.error ?? "Retry create failed"
        } else if response?.success == false {
            result = response?.error ?? "Retry create failed"
        } else {
            result = "Retry create completed."
        }
    }

    func shareIntakeTemplate() async {
        isLoading = true
        defer { isLoading = false }
        guard let fileURL = await api.downloadManualDigestIntakeTemplate() else {
            result = api.error ?? "Could not download intake template."
            return
        }
        shareTemplateFileURL = fileURL
        showTemplateShareSheet = true
    }

    func refreshNotesPipelineStatus() async {
        notesPipelineStatus = await api.fetchNotesPipelineStatus()
        if notesPipelineStatus == nil && api.error != nil {
            result = api.error
        }
    }

    func refreshOpsHealth() async {
        opsHealth = await api.fetchOpsHealth()
        if opsHealth == nil && api.error != nil {
            result = api.error
        }
    }

    func refreshIncidentQueue() async {
        incidentQueue = await api.fetchIncidentQueue(limit: 20)
        if incidentQueue == nil && api.error != nil {
            result = api.error
        }
    }

    func refreshContactsPanel() async {
        contactsStatus = await api.fetchContactsStatus()
        let watch = await api.fetchIMessageWatchlist()
        iMessageWatchlist = watch?.watchlist ?? []
        await refreshContactsList()
        await refreshRecentWorkTexts()
    }

    func refreshContactsList() async {
        let query = contactsSearch.trimmingCharacters(in: .whitespacesAndNewlines)
        let response = await api.fetchContactsList(query: query, limit: 200)
        contactsList = response?.contacts ?? []
    }

    func syncContactsAndRefresh() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.syncContactsNow()
        if response?.success == true {
            result = "Contacts synced (\(response?.contacts_count ?? 0))."
        } else {
            result = api.error ?? response?.error ?? "Contacts sync failed."
        }
        await refreshContactsPanel()
    }

    func toggleContactSelection(_ id: String) {
        if selectedContactIDs.contains(id) {
            selectedContactIDs.remove(id)
        } else {
            selectedContactIDs.insert(id)
        }
    }

    func addSelectedContactsToWatchlist() async {
        isLoading = true
        defer { isLoading = false }
        let selected = contactsList.filter { selectedContactIDs.contains($0.id) }
        let selectedPhones = selected.flatMap { $0.phones }
        let merged = Array(Set(iMessageWatchlist + selectedPhones)).sorted()
        guard !merged.isEmpty else {
            result = "No phone numbers found on selected contacts."
            return
        }
        let setResponse = await api.setIMessageWatchlist(numbers: merged, monitorAll: false)
        if setResponse?.success == true {
            result = "Updated watchlist to \(setResponse?.watchlist_count ?? merged.count) numbers."
            iMessageWatchlist = merged
        } else {
            result = api.error ?? "Could not update iMessage watchlist."
        }
    }

    func addNewClientAndMonitor() async {
        isLoading = true
        defer { isLoading = false }
        let name = newClientName.trimmingCharacters(in: .whitespacesAndNewlines)
        let phone = newClientPhone.trimmingCharacters(in: .whitespacesAndNewlines)
        let email = newClientEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        let response = await api.addClientContact(
            name: name,
            phones: [phone],
            emails: email.isEmpty ? [] : [email],
            notes: "Added from SymphonyOps mobile panel",
            autoMonitor: true
        )
        if response?.success == true {
            result = "Added client \(name) and updated monitoring."
            newClientName = ""
            newClientPhone = ""
            newClientEmail = ""
            await refreshContactsPanel()
        } else {
            result = api.error ?? response?.error ?? "Could not add client."
        }
    }

    func processIMessagesNow() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.processIMessagesNow()
        if response?.success == true {
            let monitored = response?.messages_monitored ?? 0
            let tasks = response?.tasks_created ?? 0
            result = "Processed texts. Monitored: \(monitored), tasks created: \(tasks)."
            await refreshRecentWorkTexts()
        } else {
            result = api.error ?? "iMessage process run failed."
        }
    }

    func refreshRecentWorkTexts() async {
        if isRefreshingRecentWorkTexts {
            return
        }
        isRefreshingRecentWorkTexts = true
        defer { isRefreshingRecentWorkTexts = false }
        let feed = await api.fetchRecentIMessageWork(limit: 20)
        recentWorkTexts = feed?.items ?? []
    }

    func refreshNotesTaskApprovalPanel() async {
        let links = await api.fetchNotesProjectLinks()
        notesProjectLinkRules = links?.rules ?? []
        let approvals = await api.fetchNotesTaskApprovals(status: "pending_approval", limit: 25)
        notesTaskApprovals = approvals?.items ?? []
    }

    func addNotesProjectLinkRule() async {
        isLoading = true
        defer { isLoading = false }
        let matchText = noteLinkMatchText.trimmingCharacters(in: .whitespacesAndNewlines)
        let projectName = noteLinkProjectName.trimmingCharacters(in: .whitespacesAndNewlines)
        let response = await api.addNotesProjectLink(matchText: matchText, projectName: projectName, enabled: true)
        if response?.success == true {
            result = "Added link rule: '\(matchText)' -> \(projectName)"
            noteLinkMatchText = ""
            noteLinkProjectName = ""
            await refreshNotesTaskApprovalPanel()
        } else {
            result = api.error ?? "Could not add note link rule."
        }
    }

    func approveNoteTask(_ approvalID: String) async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.approveNotesTaskApproval(approvalID: approvalID)
        if response?.success == true {
            result = "Approved note task and created Task #\(response?.task_id ?? 0)."
            await refreshNotesTaskApprovalPanel()
            await refreshIncidentQueue()
        } else {
            result = response?.error ?? api.error ?? "Could not approve note task."
        }
    }

    func rejectNoteTask(_ approvalID: String) async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.rejectNotesTaskApproval(approvalID: approvalID, reason: "Rejected from mobile panel")
        if response?.success == true {
            result = "Rejected note task approval."
            await refreshNotesTaskApprovalPanel()
        } else {
            result = response?.error ?? api.error ?? "Could not reject note task."
        }
    }

    func processNotesNow() async {
        isLoading = true
        defer { isLoading = false }
        let trimmed = notesProcessTarget.trimmingCharacters(in: .whitespacesAndNewlines)
        let noteId = Int(trimmed)
        let response = await api.processNoteNow(
            noteID: noteId,
            projectName: noteId == nil && !trimmed.isEmpty ? trimmed : nil
        )
        if let response {
            if response.success {
                result = "Notes pipeline processed now."
            } else {
                result = "Notes pipeline run finished with errors."
            }
        } else {
            result = api.error ?? "Notes pipeline run failed."
        }
        await refreshNotesPipelineStatus()
    }

    func runOpsRecoveryNow() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.runOpsRecovery(apply: true, threshold: 0.8)
        if let response {
            let detected = response.detected_count ?? 0
            let applied = response.applied_count ?? 0
            result = "Recovery run complete. Detected: \(detected), Applied: \(applied)."
        } else {
            result = api.error ?? "Recovery run failed."
        }
        await refreshOpsHealth()
        await refreshIncidentQueue()
    }

    func exportSelectedProducts(format: String) async {
        isLoading = true
        defer { isLoading = false }
        let selected = selectedDraftProducts()
        guard !selected.isEmpty else {
            result = "No selected products to export."
            return
        }
        do {
            let ts = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
            let baseName = "dtools_products_\(ts)"
            let fileURL: URL
            if format.lowercased() == "json" {
                let data = try JSONEncoder().encode(selected)
                fileURL = FileManager.default.temporaryDirectory.appendingPathComponent("\(baseName).json")
                try data.write(to: fileURL, options: .atomic)
            } else {
                let csv = csvFromProducts(selected)
                fileURL = FileManager.default.temporaryDirectory.appendingPathComponent("\(baseName).csv")
                guard let csvData = csv.data(using: .utf8) else {
                    result = "Export failed: CSV encoding error."
                    return
                }
                try csvData.write(to: fileURL, options: .atomic)
            }
            exportFileURL = fileURL
            showExportShareSheet = true
            result = "Export ready (\(format.uppercased()))."
        } catch {
            result = "Export failed: \(error.localizedDescription)"
        }
    }

    func csvFromProducts(_ products: [DToolsProductDraft]) -> String {
        let headers = [
            "brand", "model", "part_number", "category", "short_description",
            "keywords", "unit_price", "unit_cost", "msrp", "supplier"
        ]
        var lines = [headers.joined(separator: ",")]
        for p in products {
            let row: [String] = [
                p.brand ?? "",
                p.model,
                p.part_number ?? "",
                p.category ?? "",
                p.short_description ?? "",
                p.keywords ?? "",
                p.unit_price.map { String($0) } ?? "",
                p.unit_cost.map { String($0) } ?? "",
                p.msrp.map { String($0) } ?? "",
                p.supplier ?? "",
            ]
            lines.append(row.map(csvEscape).joined(separator: ","))
        }
        return lines.joined(separator: "\n")
    }

    func csvEscape(_ value: String) -> String {
        let escaped = value.replacingOccurrences(of: "\"", with: "\"\"")
        return "\"\(escaped)\""
    }

    func jobBadge(_ job: NotesPipelineJob?) -> String {
        guard let job else { return "unknown" }
        let loaded = job.loaded == true ? "loaded" : "not loaded"
        let running = job.running == true ? "running" : "stopped"
        return "\(loaded), \(running)"
    }
}

struct EditableProductDraft: Identifiable {
    let id = UUID()
    var isSelected: Bool = true
    var brand: String
    var model: String
    var partNumber: String
    var category: String
    var shortDescription: String
    var keywords: String
    var unitPrice: String
    var unitCost: String
    var msrp: String
    var supplier: String

    init(_ draft: DToolsProductDraft) {
        self.brand = draft.brand ?? "Unknown"
        self.model = draft.model
        self.partNumber = draft.part_number ?? ""
        self.category = draft.category ?? "General"
        self.shortDescription = draft.short_description ?? ""
        self.keywords = draft.keywords ?? ""
        self.unitPrice = draft.unit_price.map { String($0) } ?? ""
        self.unitCost = draft.unit_cost.map { String($0) } ?? ""
        self.msrp = draft.msrp.map { String($0) } ?? ""
        self.supplier = draft.supplier ?? ""
    }

    func toDraft() -> DToolsProductDraft {
        func asDouble(_ raw: String) -> Double? {
            let cleaned = raw.replacingOccurrences(of: "$", with: "").replacingOccurrences(of: ",", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            if cleaned.isEmpty { return nil }
            return Double(cleaned)
        }
        return DToolsProductDraft(
            brand: brand,
            model: model,
            part_number: partNumber,
            category: category,
            short_description: shortDescription,
            keywords: keywords,
            unit_price: asDouble(unitPrice),
            unit_cost: asDouble(unitCost),
            msrp: asDouble(msrp),
            supplier: supplier
        )
    }
}

struct ActionRow: View {
    let title: String
    let icon: String
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            HStack {
                Image(systemName: icon)
                    .foregroundColor(.accentColor)
                    .frame(width: 20)
                Text(title)
                    .font(.footnote)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundColor(.secondary)
                    .font(.caption)
            }
            .padding(.vertical, 4)
        }
        .foregroundColor(.primary)
        .buttonStyle(.plain)
    }
}

struct ActivityView: UIViewControllerRepresentable {
    let activityItems: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

// MARK: - Claude Approval View (Bridge: Task Board → Email → iOS → Bob)

struct ClaudeApprovalView: View {
    @EnvironmentObject var api: APIClient
    @State private var tasks: [ClaudeTask] = []
    @State private var workflows: [ClaudeWorkflow] = []
    @State private var isLoading = false
    @State private var approvingId: Int?
    @State private var message: String?
    @State private var selectedWorkflow: ClaudeWorkflow?
    @State private var copiedWorkflowId: String?
    
    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Workflow Prompts")) {
                    Text("Copy a prompt and paste into Claude Code.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    ForEach(workflows) { wf in
                        Button {
                            selectedWorkflow = wf
                        } label: {
                            HStack {
                                Text(wf.title)
                                    .foregroundColor(.primary)
                                Spacer()
                                if copiedWorkflowId == wf.id {
                                    Text("Copied")
                                        .font(.caption)
                                        .foregroundColor(.green)
                                } else {
                                    Image(systemName: "doc.on.doc")
                                        .font(.caption)
                                        .foregroundColor(.secondary)
                                }
                            }
                        }
                    }
                }
                
                Section(header: Text("Claude Approval Queue")) {
                    Text("Tasks added with type 'claude' appear here. Approve to send to Claude Code via Bob.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                
                if isLoading && tasks.isEmpty {
                    HStack {
                        Spacer()
                        ProgressView("Loading...")
                        Spacer()
                    }
                    .padding()
                }
                
                if tasks.isEmpty && !isLoading {
                    Text("No Claude tasks pending approval")
                        .foregroundColor(.secondary)
                        .frame(maxWidth: .infinity)
                        .padding()
                }
                
                ForEach(tasks) { task in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(task.title)
                                .font(.headline)
                            Spacer()
                            if approvingId == task.id {
                                ProgressView()
                            } else {
                                Button("Approve") {
                                    Task { await approve(task) }
                                }
                                .buttonStyle(.borderedProminent)
                                .tint(.orange)
                            }
                        }
                        if !task.description.isEmpty {
                            Text(task.description)
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        HStack {
                            Text(priorityLabel(task.priority))
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            Text("•")
                                .foregroundColor(.secondary)
                            Text(task.created_at)
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                }
                
                if let msg = message {
                    Section(header: Text("Result")) {
                        Text(msg)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .navigationTitle("Claude Approval")
            .refreshable {
                await loadTasks()
            }
            .task {
                await loadTasks()
            }
            .sheet(item: $selectedWorkflow) { wf in
                WorkflowPromptSheet(
                    workflow: wf,
                    onCopy: {
                        UIPasteboard.general.string = wf.prompt
                        copiedWorkflowId = wf.id
                        selectedWorkflow = nil
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                            copiedWorkflowId = nil
                        }
                    },
                    onDismiss: { selectedWorkflow = nil }
                )
            }
        }
    }
    
    func loadTasks() async {
        isLoading = true
        message = nil
        async let t = api.fetchClaudePendingTasks()
        async let w = api.fetchClaudeWorkflows()
        tasks = await t
        workflows = await w
        isLoading = false
    }
    
    func approve(_ task: ClaudeTask) async {
        approvingId = task.id
        message = nil
        let (success, msg) = await api.approveClaudeTask(id: task.id)
        message = success ? "✓ \(msg)" : "✗ \(msg)"
        approvingId = nil
        await loadTasks()
    }
    
    func priorityLabel(_ p: String) -> String {
        switch p {
        case "critical": return "🔴 Critical"
        case "high": return "🟠 High"
        case "low": return "🟢 Low"
        default: return "🟡 Medium"
        }
    }
}

struct WorkflowPromptSheet: View {
    let workflow: ClaudeWorkflow
    let onCopy: () -> Void
    let onDismiss: () -> Void
    
    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 0) {
                ScrollView {
                    Text(workflow.prompt)
                        .font(.system(.body, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                }
                .background(Color(.systemGray6))
                .cornerRadius(8)
                .padding()
                
                HStack(spacing: 12) {
                    Button("Copy to Clipboard") {
                        onCopy()
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.orange)
                    
                    Button("Done") {
                        onDismiss()
                    }
                    .buttonStyle(.bordered)
                }
                .padding()
            }
            .navigationTitle(workflow.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { onDismiss() }
                }
            }
        }
    }
}

// MARK: - Settings View

struct SettingsView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var secretsVault: SecretsVaultStore
    @State private var serverURL: String = ""
    @State private var apiTokenInput: String = ""
    @State private var authStatusMessage: String = ""
    @State private var connectionTestMessage: String = ""
    @State private var isTestingConnection = false
    @State private var isRunningOneTapFix = false
    
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Server Connection")) {
                    TextField("API URL", text: $serverURL)
                        .autocapitalization(.none)
                        .keyboardType(.URL)
                    
                    Button("Save + Test") {
                        api.setBaseURL(serverURL)
                        Task {
                            await api.checkConnection()
                            connectionTestMessage = api.lastConnectionMessage ?? ""
                            serverURL = api.baseURL
                        }
                    }

                    Button(isTestingConnection ? "Testing..." : "Test URL + Token") {
                        guard !isTestingConnection else { return }
                        isTestingConnection = true
                        Task {
                            let msg = await api.testURLAndToken()
                            await MainActor.run {
                                connectionTestMessage = msg
                                serverURL = api.baseURL
                                isTestingConnection = false
                            }
                        }
                    }
                    .disabled(isTestingConnection)
                    
                    HStack {
                        Text("Status")
                        Spacer()
                        Circle()
                            .fill(api.isConnected ? Color.green : Color.red)
                            .frame(width: 10, height: 10)
                        Text(api.isConnected ? "Connected" : "Disconnected")
                            .foregroundColor(.secondary)
                    }

                    if !connectionTestMessage.isEmpty {
                        Text(connectionTestMessage)
                            .font(.caption2)
                            .foregroundColor(api.isConnected ? .green : .red)
                    }

                    Text("If URL is localhost/127.0.0.1 and unreachable, app auto-falls back to Tailscale host.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }

                Section(header: Text("Quick Fix")) {
                    Button(isRunningOneTapFix ? "Running One-Tap Fix..." : "One-Tap Fix (Save + Fallback + Test)") {
                        guard !isRunningOneTapFix else { return }
                        isRunningOneTapFix = true
                        Task {
                            let result = await api.runOneTapConnectionFix(
                                preferredURL: serverURL,
                                tokenCandidate: apiTokenInput
                            )
                            await MainActor.run {
                                connectionTestMessage = result
                                authStatusMessage = api.apiTokenConfigured
                                    ? "Token stored in Keychain."
                                    : "No token in Keychain yet."
                                apiTokenInput = ""
                                serverURL = api.baseURL
                                isRunningOneTapFix = false
                            }
                        }
                    }
                    .disabled(isRunningOneTapFix)
                    .buttonStyle(.borderedProminent)

                    Text("Runs full recovery in one step: saves token if entered, tests URL, falls back to Tailscale host, and re-tests.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }

                Section(header: Text("API Auth (Keychain)")) {
                    SecureField("X-Symphony-Token", text: $apiTokenInput)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled(true)

                    HStack {
                        Button("Save Token") {
                            api.setAPIToken(apiTokenInput)
                            Task {
                                let msg = await api.testURLAndToken()
                                await MainActor.run {
                                    apiTokenInput = ""
                                    authStatusMessage = "Token saved to Keychain."
                                    connectionTestMessage = msg
                                    serverURL = api.baseURL
                                }
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(apiTokenInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                        Button("Clear Token", role: .destructive) {
                            api.clearAPIToken()
                            apiTokenInput = ""
                            authStatusMessage = "Keychain token cleared."
                        }
                        .buttonStyle(.bordered)
                    }

                    HStack {
                        Text("Stored")
                        Spacer()
                        Circle()
                            .fill(api.apiTokenConfigured ? Color.green : Color.gray)
                            .frame(width: 10, height: 10)
                        Text(api.apiTokenConfigured ? "Yes" : "No")
                            .foregroundColor(.secondary)
                    }

                    if !authStatusMessage.isEmpty {
                        Text(authStatusMessage)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }

                    Text("Token is stored in iOS Keychain only (WhenUnlockedThisDeviceOnly).")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }

                Section(header: Text("API Keys + Secrets Vault")) {
                    NavigationLink {
                        SecretsVaultView()
                            .environmentObject(secretsVault)
                    } label: {
                        Label("Open Encrypted Secrets Vault", systemImage: "lock.shield")
                    }

                    Text("Use Vault records for API keys/tokens instead of notes. Values are encrypted at rest and managed with biometric-gated actions.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                
                Section(header: Text("Presets")) {
                    Button("Use Tailscale (Anywhere)") {
                        serverURL = "http://100.89.1.51:8420"
                        api.setBaseURL(serverURL)
                        Task {
                            await api.checkConnection()
                            connectionTestMessage = api.lastConnectionMessage ?? ""
                            serverURL = api.baseURL
                        }
                    }
                    
                    Button("Use Local Network (Home WiFi)") {
                        serverURL = "http://192.168.1.109:8420"
                        api.setBaseURL(serverURL)
                        Task {
                            await api.checkConnection()
                            connectionTestMessage = api.lastConnectionMessage ?? ""
                            serverURL = api.baseURL
                        }
                    }
                    
                    Button("Use Localhost (Simulator)") {
                        serverURL = "http://127.0.0.1:8420"
                        api.setBaseURL(serverURL)
                        Task {
                            await api.checkConnection()
                            connectionTestMessage = api.lastConnectionMessage ?? ""
                            serverURL = api.baseURL
                        }
                    }
                }
                
                Section(header: Text("Local AI")) {
                    HStack {
                        Text("Ollama")
                        Spacer()
                        Circle()
                            .fill(api.ollamaAvailable ? Color.green : Color.gray)
                            .frame(width: 10, height: 10)
                        Text(api.ollamaAvailable ? "Available" : "Offline")
                            .foregroundColor(.secondary)
                    }
                    
                    HStack {
                        Text("LM Studio")
                        Spacer()
                        Circle()
                            .fill(api.lmStudioAvailable ? Color.green : Color.gray)
                            .frame(width: 10, height: 10)
                        Text(api.lmStudioAvailable ? "Available" : "Offline")
                            .foregroundColor(.secondary)
                    }
                    
                    if api.ollamaAvailable {
                        Text("Ollama model: llama3.2:3b")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                    
                    Toggle("Prefer Local AI", isOn: Binding(
                        get: { api.preferLocalAI },
                        set: { api.setPreferLocalAI($0) }
                    ))
                    
                    Text("Uses Ollama or LM Studio when available, saves cloud credits")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                
                Section(header: Text("Ask Bob Model")) {
                    Picker("Default source", selection: Binding(
                        get: { api.preferredAISource },
                        set: { api.setPreferredAISource($0) }
                    )) {
                        Text("Auto").tag("auto")
                        Text("Cortex").tag("cortex")
                        Text("Ollama").tag("ollama")
                        Text("LM Studio").tag("lm_studio")
                        Text("GPT-4o-mini").tag("gpt-4o-mini")
                        Text("Perplexity").tag("perplexity")
                    }
                    .pickerStyle(.menu)
                    Text("Override in Ask Bob tab via the source menu")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                
                Section(header: Text("About")) {
                    HStack {
                        Text("Version")
                        Spacer()
                        Text("1.0.0")
                            .foregroundColor(.secondary)
                    }
                    
                    HStack {
                        Text("API Endpoint")
                        Spacer()
                        Text(api.baseURL)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .navigationTitle("Settings")
            .onAppear {
                serverURL = api.baseURL
                connectionTestMessage = api.lastConnectionMessage ?? ""
            }
        }
    }
}

// MARK: - Dashboard Components

struct StatusPill: View {
    let isConnected: Bool
    let ollamaAvailable: Bool
    let lmStudioAvailable: Bool
    let onRetry: () -> Void
    
    private var aiStatus: String {
        guard isConnected else { return "—" }
        if ollamaAvailable || lmStudioAvailable { return "AI ready" }
        return "AI offline"
    }
    
    private var aiColor: Color {
        guard isConnected else { return .gray }
        if ollamaAvailable || lmStudioAvailable { return .green }
        return .red
    }
    
    var body: some View {
        HStack(spacing: 16) {
            HStack(spacing: 8) {
                Circle()
                    .fill(isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                Text(isConnected ? "Connected" : "Offline")
                    .font(.subheadline)
                    .fontWeight(.medium)
            }
            
            if isConnected {
                Rectangle()
                    .fill(Color(.separator))
                    .frame(width: 1, height: 16)
                
                HStack(spacing: 8) {
                    Circle()
                        .fill(aiColor)
                        .frame(width: 8, height: 8)
                    Text(aiStatus)
                        .font(.subheadline)
                        .fontWeight(.medium)
                }
            }
            
            Spacer()
            
            if isConnected && !ollamaAvailable && !lmStudioAvailable {
                Button("Retry") {
                    onRetry()
                }
                .font(.caption)
                .fontWeight(.semibold)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color(.secondarySystemGroupedBackground))
        .cornerRadius(16)
    }
}

struct PrimaryActionCard: View {
    let title: String
    let subtitle: String
    let icon: String
    let color: Color
    let isSelected: Bool
    let isLoading: Bool
    let statusLabel: String?
    let statusColor: Color?
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .center) {
                    Image(systemName: icon)
                        .font(.title3)
                        .foregroundColor(color)
                    Spacer()
                    if isLoading {
                        ProgressView()
                            .scaleEffect(0.85)
                    }
                }
                Text(title)
                    .font(.headline)
                    .fontWeight(.semibold)
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
                if let statusLabel, let statusColor {
                    Text(statusLabel)
                        .font(.caption2)
                        .fontWeight(.semibold)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(statusColor.opacity(0.18))
                        .foregroundColor(statusColor)
                        .clipShape(Capsule())
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(minHeight: 108)
            .padding(20)
            .background(Color(.secondarySystemGroupedBackground))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(isSelected ? Color.orange : Color.clear, lineWidth: 2)
            )
            .cornerRadius(16)
        }
        .buttonStyle(.plain)
    }
}

struct CompactStatsBar: View {
    let proposals: Int
    let knowledge: Int
    let cost: Int
    let servicesUp: Int
    let servicesTotal: Int
    
    var body: some View {
        HStack(spacing: 0) {
            StatPill(value: "\(proposals)", label: "Proposals")
            Divider()
                .frame(height: 24)
            StatPill(value: "\(knowledge)", label: "Knowledge")
            Divider()
                .frame(height: 24)
            StatPill(value: "$\(cost)", label: "Cost")
            Divider()
                .frame(height: 24)
            StatPill(value: "\(servicesUp)/\(servicesTotal)", label: "Services")
        }
        .padding(.vertical, 14)
        .padding(.horizontal, 16)
        .background(Color(.secondarySystemGroupedBackground))
        .cornerRadius(16)
    }
}

struct StatPill: View {
    let value: String
    let label: String
    
    var body: some View {
        VStack(spacing: 2) {
            Text(value)
                .font(.subheadline)
                .fontWeight(.semibold)
            Text(label)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

struct ToolChip: View {
    let title: String
    let icon: String
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.caption)
                Text(title)
                    .font(.subheadline)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(Color(.tertiarySystemGroupedBackground))
            .cornerRadius(12)
        }
        .buttonStyle(.plain)
    }
}

struct ResultCard: View {
    let text: String
    let onDismiss: () -> Void
    
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Result")
                    .font(.subheadline)
                    .fontWeight(.semibold)
                Spacer()
                Button("Dismiss", action: onDismiss)
                    .font(.caption)
            }
            Text(text)
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground))
        .cornerRadius(16)
    }
}

// MARK: - Reusable Components (legacy, kept for other views)

struct LocalModelsOfflineBanner: View {
    let ollamaDown: Bool
    let lmStudioDown: Bool
    let onRetry: () -> Void
    
    private var message: String {
        var parts: [String] = []
        if ollamaDown { parts.append("Ollama (Betty)") }
        if lmStudioDown { parts.append("LM Studio") }
        return "Local AI offline: " + parts.joined(separator: ", ")
    }
    
    var body: some View {
        HStack {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(.orange)
            Text(message)
                .font(.subheadline)
                .fontWeight(.medium)
            Spacer()
            Button("Retry") {
                onRetry()
            }
            .font(.caption)
            .fontWeight(.semibold)
        }
        .padding()
        .background(Color.orange.opacity(0.15))
        .cornerRadius(12)
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.orange.opacity(0.5), lineWidth: 1)
        )
        .padding(.horizontal)
    }
}

struct ConnectionStatusCard: View {
    let isConnected: Bool
    
    var body: some View {
        HStack {
            Circle()
                .fill(isConnected ? Color.green : Color.red)
                .frame(width: 12, height: 12)
            
            Text(isConnected ? "Connected to Bob" : "Disconnected")
                .font(.subheadline)
                .fontWeight(.medium)
            
            Spacer()
            
            if isConnected {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundColor(.green)
            } else {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundColor(.orange)
            }
        }
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(12)
        .padding(.horizontal)
    }
}

struct StatCard: View {
    let title: String
    let value: String
    let subtitle: String
    let icon: String
    let color: Color
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: icon)
                    .foregroundColor(color)
                Spacer()
            }
            
            Text(value)
                .font(.title)
                .fontWeight(.bold)
            
            Text(title)
                .font(.subheadline)
                .fontWeight(.medium)
            
            Text(subtitle)
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(12)
    }
}

struct QuickActionButton: View {
    let title: String
    let icon: String
    let color: Color
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundColor(color)
                
                Text(title)
                    .font(.caption)
                    .foregroundColor(.primary)
            }
            .frame(width: 70, height: 70)
            .background(Color(.systemGray6))
            .cornerRadius(12)
        }
    }
}

// MARK: - Mission Control & Neural Map WebViews

struct WebViewWrapper: UIViewRepresentable {
    let url: URL
    
    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.scrollView.bounces = true
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.load(URLRequest(url: url))
        return webView
    }
    
    func updateUIView(_ webView: WKWebView, context: Context) {}
}

struct MissionControlWebView: View {
    @EnvironmentObject var api: APIClient
    
    var body: some View {
        NavigationView {
            Group {
                if let url = URL(string: api.missionControlURL) {
                    WebViewWrapper(url: url)
                } else {
                    Text("Invalid Mission Control URL")
                        .foregroundColor(.secondary)
                }
            }
            .navigationTitle("Mission Control")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

struct NeuralMapWebView: View {
    @EnvironmentObject var api: APIClient
    
    var body: some View {
        NavigationView {
            Group {
                if let url = URL(string: "\(api.missionControlURL)/neural") {
                    WebViewWrapper(url: url)
                } else {
                    Text("Invalid Neural Map URL")
                        .foregroundColor(.secondary)
                }
            }
            .navigationTitle("Neural Map")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

// MARK: - Preview

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
            .environmentObject(APIClient())
    }
}

