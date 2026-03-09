import SwiftUI
import WebKit
import UniformTypeIdentifiers
import UIKit

struct ContentView: View {
    @EnvironmentObject var api: APIClient
    @State private var selectedTab = 0
    @StateObject private var secretsVault = SecretsVaultStore()
    
    var body: some View {
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
        .accentColor(Color.orange)
        .task {
            await api.checkConnection()
            if api.isConnected {
                await api.fetchDashboard()
            }
            await api.checkOllama()
            await api.checkLMStudio()
            await api.fetchAIStatus()
        }
    }
}

struct OpsHubView: View {
    @EnvironmentObject var secretsVault: SecretsVaultStore

    var body: some View {
        NavigationStack {
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
            }
            .navigationTitle("Ops Hub")
        }
    }
}

// MARK: - Dashboard View

struct DashboardView: View {
    @EnvironmentObject var api: APIClient
    @State private var quickActionResult: String?
    @State private var quickActionLoading = false
    @State private var taskTitle = ""
    @State private var taskDescription = ""
    @State private var taskType = "research"
    @State private var taskPriority = "medium"
    @State private var homeClaudePending: [ClaudeTask] = []
    @State private var homeNotesApprovals: [NotesTaskApprovalItem] = []
    @State private var taskBoardLoading = false
    
    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 28) {
                    // Status — compact pill
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
                    
                    // Primary actions — 2x2 grid
                    VStack(spacing: 12) {
                        HStack(spacing: 12) {
                            PrimaryActionCard(
                                title: "Morning",
                                icon: "sunrise.fill",
                                color: Color(red: 1, green: 0.85, blue: 0.4)
                            ) {
                                Task { await runQuickAction(name: "Morning") { await api.runMorningChecklist() } }
                            }
                            .disabled(quickActionLoading)
                            
                            PrimaryActionCard(
                                title: "Check Bids",
                                icon: "hammer.fill",
                                color: Color(red: 0.35, green: 0.55, blue: 0.95)
                            ) {
                                Task { await runQuickAction(name: "Bids") { await api.checkBids() } }
                            }
                            .disabled(quickActionLoading)
                        }
                        HStack(spacing: 12) {
                            PrimaryActionCard(
                                title: "Website",
                                icon: "globe.americas.fill",
                                color: Color(red: 0.3, green: 0.7, blue: 0.5)
                            ) {
                                Task { await runWebsiteAction() }
                            }
                            .disabled(quickActionLoading)
                            
                            PrimaryActionCard(
                                title: "Markup",
                                icon: "pencil.and.outline",
                                color: Color(red: 0.95, green: 0.6, blue: 0.3)
                            ) {
                                let url = api.markupURL ?? api.fallbackMarkupURL
                                UIApplication.shared.open(url)
                            }
                        }
                    }
                    .padding(.horizontal, 20)

                    // Task Board quick panel
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("Task Board")
                                .font(.subheadline)
                                .fontWeight(.semibold)
                                .foregroundColor(.secondary)
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

                        if !homeClaudePending.isEmpty {
                            Text("Claude approvals (\(homeClaudePending.count))")
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
                            Text("Note approvals (\(homeNotesApprovals.count))")
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
                    }
                    .padding(.horizontal, 20)
                    
                    // Stats — single compact row
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
                    
                    // Social / X — same as Telegram
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Social / X")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                            .foregroundColor(.secondary)
                            .padding(.horizontal, 4)
                        
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
                    }
                    .padding(.horizontal, 20)
                    
                    // Tools — verify actions
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Tools")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                            .foregroundColor(.secondary)
                            .padding(.horizontal, 4)
                        
                        HStack(spacing: 10) {
                            ToolChip(
                                title: "Verify Ollama",
                                icon: "checkmark.shield.fill"
                            ) {
                                Task { await runVerifyOllama() }
                            }
                            .disabled(quickActionLoading)
                            
                            ToolChip(
                                title: "Verify LM Studio",
                                icon: "checkmark.shield.fill"
                            ) {
                                Task { await runVerifyLMStudio() }
                            }
                            .disabled(quickActionLoading)
                        }
                    }
                    .padding(.horizontal, 20)
                    
                    // Result / Loading / Error
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
                await api.fetchAIStatus()
                await refreshHomeTaskBoard()
            }
            .task {
                await api.fetchMarkupURL()
                await refreshHomeTaskBoard()
            }
            .onAppear {
                Task { await api.fetchAIStatus() }
            }
        }
    }
    
    func runQuickAction(name: String, action: () async -> CommandResult?) async {
        quickActionLoading = true
        quickActionResult = nil
        let result = await action()
        quickActionResult = result?.output ?? result?.error ?? (result?.success == true ? "Done" : "Failed")
        quickActionLoading = false
    }
    
    func runWebsiteAction() async {
        quickActionLoading = true
        quickActionResult = nil
        let result = await api.checkWebsite()
        if let status = result {
            let upCount = status.sites.values.filter { $0.uptime.status == "up" }.count
            let total = status.sites.count
            quickActionResult = "\(upCount)/\(total) sites up"
        } else {
            quickActionResult = api.error ?? "Failed"
        }
        quickActionLoading = false
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
        homeClaudePending = await claude
        homeNotesApprovals = (await approvals)?.items ?? []
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
    @State private var editableProducts: [EditableProductDraft] = []
    @State private var manualDigestProjectName = ""
    @State private var manualDigestRunAI = true
    @State private var showManualDigestImporter = false
    @State private var selectedManualDigestFiles: [URL] = []
    @State private var manualDigestResponse: ProjectManualDigestResponse?
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
                }

                if actionWorkspace == .dailyOps {
                Section(header: Text("Automation Health")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Unified ops status + one-tap autonomous recovery.")
                            .font(.caption)
                            .foregroundColor(.secondary)

                        HStack {
                            Button {
                                Task { await runOpsRecoveryNow() }
                            } label: {
                                HStack {
                                    Image(systemName: "cross.case.fill")
                                    Text("Run Recovery Now")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(isLoading)

                            Button {
                                Task { await refreshOpsHealth() }
                            } label: {
                                HStack {
                                    Image(systemName: "arrow.clockwise")
                                    Text("Refresh Ops")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)

                            Button {
                                Task { await refreshIncidentQueue() }
                            } label: {
                                HStack {
                                    Image(systemName: "list.bullet.clipboard")
                                    Text("Open Incident Queue")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)
                        }

                        if let health = opsHealth {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Ops: \(opsStatusLabel(health.status))")
                                    .font(.caption2)
                                    .foregroundColor(opsStatusColor(health.status))
                                Text("Build Guardian: \((health.ios_build_guardian?.overall_ok ?? false) ? "OK" : "Check")")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                Text("Recovery: detected \(health.autonomous_recovery?.detected_count ?? 0), applied \(health.autonomous_recovery?.applied_count ?? 0)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                if let problems = health.problems, !problems.isEmpty {
                                    Text("Problems: \(problems.prefix(4).joined(separator: ", "))")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                        }

                        if let queue = incidentQueue {
                            Divider()
                            Text("Incident Queue (\(queue.count))")
                                .font(.caption)
                                .fontWeight(.semibold)
                            if queue.incidents.isEmpty {
                                Text("No high-priority troubleshooting incidents.")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            } else {
                                ForEach(queue.incidents.prefix(8)) { incident in
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("[\(incident.priority.uppercased())] #\(incident.id) \(incident.title)")
                                            .font(.caption2)
                                            .fontWeight(.semibold)
                                        Text("Status: \(incident.status)\(incident.assigned_to == nil ? "" : " • @\(incident.assigned_to!)")")
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                    }
                                }
                            }
                        }
                    }
                }

                Section(header: Text("Notes Automation")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Force-process one note by ID, or leave blank to process latest changes now.")
                            .font(.caption)
                            .foregroundColor(.secondary)

                        TextField("Note ID (optional) or project hint", text: $notesProcessTarget)
                            .textFieldStyle(.roundedBorder)

                        HStack {
                            Button {
                                Task { await processNotesNow() }
                            } label: {
                                HStack {
                                    Image(systemName: "bolt.horizontal.circle")
                                    Text("Process Note Now")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(isLoading)

                            Button {
                                Task { await refreshNotesPipelineStatus() }
                            } label: {
                                HStack {
                                    Image(systemName: "arrow.clockwise")
                                    Text("Refresh Status")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)
                        }

                        if let status = notesPipelineStatus {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Watcher: \(jobBadge(status.jobs?.notes_watcher))")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                Text("Incoming Tasks: \(jobBadge(status.jobs?.incoming_tasks))")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                Text("Photo Sync: \(jobBadge(status.jobs?.notes_sync_photos))")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                if let count = status.state?.notes_watcher_processed_count {
                                    Text("Processed notes: \(count)")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                        }
                    }
                }

                Section(header: Text("Contacts + iMessages")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Pick existing contacts to monitor, or add new client contacts and auto-monitor their numbers.")
                            .font(.caption)
                            .foregroundColor(.secondary)

                        HStack {
                            Button {
                                Task { await syncContactsAndRefresh() }
                            } label: {
                                HStack {
                                    Image(systemName: "person.2.badge.gearshape")
                                    Text("Sync Contacts")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)

                            Button {
                                Task { await refreshContactsPanel() }
                            } label: {
                                HStack {
                                    Image(systemName: "arrow.clockwise")
                                    Text("Refresh")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)

                            Button {
                                Task { await processIMessagesNow() }
                            } label: {
                                HStack {
                                    Image(systemName: "bolt.badge.clock")
                                    Text("Process Texts Now")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(isLoading)
                        }

                        if let count = contactsStatus?.contacts?.contacts_count {
                            Text("Contacts indexed: \(count) • Watchlist: \(iMessageWatchlist.count)")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }

                        TextField("Search contacts by name/phone/email", text: $contactsSearch)
                            .textFieldStyle(.roundedBorder)
                            .onSubmit {
                                Task { await refreshContactsList() }
                            }

                        if !contactsList.isEmpty {
                            ForEach(contactsList.prefix(8)) { contact in
                                Button {
                                    toggleContactSelection(contact.id)
                                } label: {
                                    HStack {
                                        Image(systemName: selectedContactIDs.contains(contact.id) ? "checkmark.circle.fill" : "circle")
                                            .foregroundColor(selectedContactIDs.contains(contact.id) ? .green : .secondary)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(contact.name)
                                                .font(.caption)
                                            Text(contact.phones.first ?? contact.emails.first ?? "No phone/email")
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                        }
                                        Spacer()
                                        if !contact.linked_projects.isEmpty {
                                            Text(contact.linked_projects[0])
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                        }
                                    }
                                }
                                .buttonStyle(.plain)
                            }

                            Button {
                                Task { await addSelectedContactsToWatchlist() }
                            } label: {
                                HStack {
                                    Image(systemName: "phone.badge.plus")
                                    Text("Monitor Selected Contacts")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(isLoading || selectedContactIDs.isEmpty)
                        }

                        Divider()
                        Text("Add New Client")
                            .font(.caption)
                            .fontWeight(.semibold)
                        TextField("Client name", text: $newClientName)
                            .textFieldStyle(.roundedBorder)
                        TextField("Client phone", text: $newClientPhone)
                            .textFieldStyle(.roundedBorder)
                            .keyboardType(.phonePad)
                        TextField("Client email (optional)", text: $newClientEmail)
                            .textFieldStyle(.roundedBorder)
                            .keyboardType(.emailAddress)

                        Button {
                            Task { await addNewClientAndMonitor() }
                        } label: {
                            HStack {
                                Image(systemName: "person.badge.plus")
                                Text("Add Client + Monitor")
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isLoading || newClientName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || newClientPhone.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                        Divider()
                        HStack {
                            Text("Recent Work Texts")
                                .font(.caption)
                                .fontWeight(.semibold)
                            Spacer()
                            Button {
                                Task { await refreshRecentWorkTexts() }
                            } label: {
                                Label("Refresh Feed", systemImage: "arrow.clockwise")
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .disabled(isLoading)
                        }

                        if recentWorkTexts.isEmpty {
                            Text("No monitored texts yet.")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        } else {
                            ForEach(recentWorkTexts.prefix(10)) { item in
                                VStack(alignment: .leading, spacing: 3) {
                                    HStack {
                                        Text(item.contact_name ?? item.handle ?? "Unknown sender")
                                            .font(.caption)
                                            .fontWeight(.semibold)
                                        Spacer()
                                        if let taskID = item.task_id {
                                            Text("Task #\(taskID)")
                                                .font(.caption2)
                                                .foregroundColor(.green)
                                        } else {
                                            Text("Parsed")
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                        }
                                    }
                                    Text(item.text ?? "")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                        .lineLimit(2)
                                    if let projects = item.linked_projects, !projects.isEmpty {
                                        Text("Project: \(projects[0])")
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                    }
                                }
                                .padding(.vertical, 2)
                            }
                        }
                    }
                }

                Section(header: Text("Project Note Linking + Approval")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Link note text to a project, auto-parse on ingest, then approve before task creation.")
                            .font(.caption)
                            .foregroundColor(.secondary)

                        TextField("Match text (e.g. mitchell)", text: $noteLinkMatchText)
                            .textFieldStyle(.roundedBorder)
                        TextField("Project name (e.g. Mitchell Residence)", text: $noteLinkProjectName)
                            .textFieldStyle(.roundedBorder)

                        HStack {
                            Button {
                                Task { await addNotesProjectLinkRule() }
                            } label: {
                                HStack {
                                    Image(systemName: "link.badge.plus")
                                    Text("Add Link Rule")
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(isLoading || noteLinkMatchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || noteLinkProjectName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                            Button {
                                Task { await refreshNotesTaskApprovalPanel() }
                            } label: {
                                HStack {
                                    Image(systemName: "arrow.clockwise")
                                    Text("Refresh Queue")
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)
                        }

                        if !notesProjectLinkRules.isEmpty {
                            Text("Link rules: \(notesProjectLinkRules.count)")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            ForEach(notesProjectLinkRules.prefix(4)) { rule in
                                Text("• '\(rule.match_text)' -> \(rule.project_name)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                        }

                        Divider()
                        Text("Pending Approvals (\(notesTaskApprovals.count))")
                            .font(.caption)
                            .fontWeight(.semibold)

                        if notesTaskApprovals.isEmpty {
                            Text("No pending note approvals.")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        } else {
                            ForEach(notesTaskApprovals.prefix(6)) { item in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(item.note_title ?? "Untitled note")
                                        .font(.caption)
                                        .fontWeight(.semibold)
                                    Text("Project: \(item.project_name ?? "Unknown")")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                    HStack {
                                        Button("Approve") {
                                            Task { await approveNoteTask(item.id) }
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .controlSize(.small)
                                        .disabled(isLoading)
                                        Button("Reject") {
                                            Task { await rejectNoteTask(item.id) }
                                        }
                                        .buttonStyle(.bordered)
                                        .controlSize(.small)
                                        .disabled(isLoading)
                                    }
                                }
                            }
                        }
                    }
                }
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
            await api.fetchMarkupURL()
            await refreshNotesPipelineStatus()
            await refreshOpsHealth()
            await refreshIncidentQueue()
            await refreshContactsPanel()
            await refreshNotesTaskApprovalPanel()
        }
        .task {
            // Lightweight live feed polling while Actions view is visible.
            while !Task.isCancelled {
                if scenePhase == .active && actionWorkspace == .dailyOps {
                    await refreshRecentWorkTexts()
                }
                try? await Task.sleep(nanoseconds: 30_000_000_000)
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
    let icon: String
    let color: Color
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 12) {
                Image(systemName: icon)
                    .font(.title)
                    .foregroundColor(color)
                Text(title)
                    .font(.subheadline)
                    .fontWeight(.semibold)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
            .background(Color(.secondarySystemGroupedBackground))
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

