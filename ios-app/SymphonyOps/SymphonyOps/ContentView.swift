import SwiftUI
import WebKit

struct ContentView: View {
    @EnvironmentObject var api: APIClient
    @State private var selectedTab = 0
    
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
            
            LeadsView()
                .tabItem {
                    Label("Leads", systemImage: "person.3")
                }
                .tag(2)
            
            ActionsView()
                .tabItem {
                    Label("Actions", systemImage: "bolt.fill")
                }
                .tag(3)
            
            ClaudeApprovalView()
                .tabItem {
                    Label("Claude", systemImage: "brain.head.profile")
                }
                .tag(4)
            
            MissionControlWebView()
                .tabItem {
                    Label("Mission Control", systemImage: "antenna.radiowaves.left.and.right")
                }
                .tag(5)
            
            NeuralMapWebView()
                .tabItem {
                    Label("Neural Map", systemImage: "brain")
                }
                .tag(6)
            
            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gear")
                }
                .tag(7)
            
            FactsView()
                .tabItem {
                    Label("Facts", systemImage: "doc.text.fill")
                }
                .tag(8)
        }
        .accentColor(Color.orange)
        .task {
            await api.checkConnection()
            await api.fetchDashboard()
            await api.checkOllama()
            await api.checkLMStudio()
            await api.fetchAIStatus()
        }
    }
}

// MARK: - Dashboard View

struct DashboardView: View {
    @EnvironmentObject var api: APIClient
    @State private var quickActionResult: String?
    @State private var quickActionLoading = false
    
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
            }
            .task { await api.fetchMarkupURL() }
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
            let (answer, source) = await api.askAI(question: userMessage)
            await MainActor.run {
                chatHistory.append(ChatMessage(
                    role: "assistant",
                    content: answer ?? "Sorry, I couldn't process that request.",
                    source: source
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
    let timestamp = Date()
}

struct ChatBubble: View {
    let message: ChatMessage
    
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
    @State private var searchQuery = ""
    @State private var result: String?
    @State private var isLoading = false
    
    var markupURL: URL {
        api.markupURL ?? api.fallbackMarkupURL
    }
    
    var body: some View {
        NavigationView {
            List {
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
                
                if let result = result {
                    Section(header: Text("Result")) {
                        ScrollView {
                            Text(result)
                                .font(.system(.caption, design: .monospaced))
                        }
                        .frame(maxHeight: 300)
                    }
                }
                
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
                
                Section(header: Text("Quick Commands")) {
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
            .navigationTitle("Actions")
        }
        .task { await api.fetchMarkupURL() }
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
                Text(title)
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundColor(.secondary)
            }
        }
        .foregroundColor(.primary)
    }
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
    @State private var serverURL: String = ""
    
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Server Connection")) {
                    TextField("API URL", text: $serverURL)
                        .autocapitalization(.none)
                        .keyboardType(.URL)
                    
                    Button("Save & Connect") {
                        api.setBaseURL(serverURL)
                        Task { await api.checkConnection() }
                    }
                    
                    HStack {
                        Text("Status")
                        Spacer()
                        Circle()
                            .fill(api.isConnected ? Color.green : Color.red)
                            .frame(width: 10, height: 10)
                        Text(api.isConnected ? "Connected" : "Disconnected")
                            .foregroundColor(.secondary)
                    }
                }
                
                Section(header: Text("Presets")) {
                    Button("Use Tailscale (Anywhere)") {
                        serverURL = "http://bobs-mac-mini:8420"
                        api.setBaseURL(serverURL)
                        Task { await api.checkConnection() }
                    }
                    
                    Button("Use Local Network (Home WiFi)") {
                        serverURL = "http://192.168.1.109:8420"
                        api.setBaseURL(serverURL)
                        Task { await api.checkConnection() }
                    }
                    
                    Button("Use Localhost (Simulator)") {
                        serverURL = "http://127.0.0.1:8420"
                        api.setBaseURL(serverURL)
                        Task { await api.checkConnection() }
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

