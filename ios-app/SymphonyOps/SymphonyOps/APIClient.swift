import Foundation
import Combine

extension UserDefaults {
    func contains(key: String) -> Bool {
        return object(forKey: key) != nil
    }
}

/// API Client for Symphony AI Mobile API
class APIClient: ObservableObject {
    @Published var isConnected = false
    @Published var services: [ServiceStatus] = []
    @Published var stats: DashboardStats?
    @Published var error: String?
    @Published var ollamaAvailable = false
    @Published var lmStudioAvailable = false
    @Published var preferLocalAI = true
    @Published var aiBackendStatus: AIBackendStatus?
    @Published var preferredAISource: String = "auto"
    @Published var markupURL: URL?

    // Configure your server URL here
    // Tailscale: http://bobs-mac-mini:8420 (works anywhere)
    // Local: http://192.168.1.109:8420 (home WiFi only)
    var baseURL: String {
        UserDefaults.standard.string(forKey: "api_base_url") ?? "http://bobs-mac-mini:8420"
    }
    
    var ollamaURL: String {
        // Derive Ollama URL from base URL (same host, port 11434)
        let host = baseURL
            .replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "https://", with: "")
            .components(separatedBy: ":").first ?? "localhost"
        return "http://\(host):11434"
    }
    
    func setBaseURL(_ url: String) {
        UserDefaults.standard.set(url, forKey: "api_base_url")
        Task {
            await checkOllama()
            await checkLMStudio()
            await fetchAIStatus()
        }
    }
    
    func setPreferLocalAI(_ prefer: Bool) {
        preferLocalAI = prefer
        UserDefaults.standard.set(prefer, forKey: "prefer_local_ai")
    }
    
    func setPreferredAISource(_ source: String) {
        preferredAISource = source
        UserDefaults.standard.set(source, forKey: "preferred_ai_source")
    }
    
    func loadPreferences() {
        preferLocalAI = UserDefaults.standard.bool(forKey: "prefer_local_ai")
        if !UserDefaults.standard.contains(key: "prefer_local_ai") {
            preferLocalAI = true // Default to local
        }
        preferredAISource = UserDefaults.standard.string(forKey: "preferred_ai_source") ?? "auto"
    }
    
    var lmStudioURL: String {
        let host = baseURL
            .replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "https://", with: "")
            .components(separatedBy: ":").first ?? "localhost"
        return "http://\(host):1234"
    }

    /// Mission Control + Neural Map (event server on port 8765)
    var missionControlURL: String {
        let host = baseURL
            .replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "https://", with: "")
            .components(separatedBy: ":").first ?? "localhost"
        return "http://\(host):8765"
    }

    /// Fallback markup URL when API doesn't return one (derived from baseURL)
    var fallbackMarkupURL: URL {
        let host = baseURL
            .replacingOccurrences(of: "http://", with: "")
            .replacingOccurrences(of: "https://", with: "")
            .components(separatedBy: ":").first ?? "localhost"
        return URL(string: "http://\(host):8091")!
    }

    // MARK: - Health Check
    
    func checkConnection() async {
        do {
            let url = URL(string: "\(baseURL)/health")!
            let (_, response) = try await URLSession.shared.data(from: url)
            if let httpResponse = response as? HTTPURLResponse {
                await MainActor.run {
                    self.isConnected = httpResponse.statusCode == 200
                }
            }
        } catch {
            await MainActor.run {
                self.isConnected = false
                self.error = error.localizedDescription
            }
        }
    }
    
    // MARK: - Dashboard
    
    func fetchDashboard() async {
        do {
            let url = URL(string: "\(baseURL)/dashboard")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let dashboard = try JSONDecoder().decode(DashboardResponse.self, from: data)

            await MainActor.run {
                self.services = dashboard.services
                self.stats = dashboard.stats
                self.isConnected = true
                self.error = nil
            }
            await fetchMarkupURL()
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
        }
    }

    func fetchMarkupURL() async {
        struct MarkupURLResponse: Decodable {
            let url: String?
            let httpsUrl: String?
        }
        do {
            let url = URL(string: "\(baseURL)/markup/url")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let resp = try JSONDecoder().decode(MarkupURLResponse.self, from: data)
            let preferred = resp.httpsUrl ?? resp.url
            await MainActor.run {
                self.markupURL = preferred.flatMap { URL(string: $0) }
            }
        } catch {
            await MainActor.run { self.markupURL = nil }
        }
    }
    
    // MARK: - Services
    
    func fetchServices() async {
        do {
            let url = URL(string: "\(baseURL)/services")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let response = try JSONDecoder().decode(ServicesResponse.self, from: data)
            
            await MainActor.run {
                self.services = response.services
            }
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
        }
    }
    
    // MARK: - Bids
    
    func checkBids() async -> CommandResult? {
        return await runCommand("/bids")
    }
    
    func listBids() async -> CommandResult? {
        return await runCommand("/bids/list")
    }
    
    // MARK: - Proposals
    
    func fetchProposals() async -> [Proposal]? {
        do {
            let url = URL(string: "\(baseURL)/proposals")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let response = try JSONDecoder().decode(ProposalsResponse.self, from: data)
            return response.proposals
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
    // MARK: - Research
    
    func search(query: String) async -> CommandResult? {
        return await postCommand(endpoint: "/research", body: ["query": query])
    }
    
    // MARK: - Morning Checklist
    
    func runMorningChecklist() async -> CommandResult? {
        return await runCommand("/morning")
    }
    
    // MARK: - Website
    
    func checkWebsite() async -> WebsiteStatus? {
        do {
            let url = URL(string: "\(baseURL)/website/status")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(WebsiteStatus.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
    // MARK: - Subscriptions
    
    func fetchSubscriptions() async -> [Subscription]? {
        do {
            let url = URL(string: "\(baseURL)/subscriptions")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let response = try JSONDecoder().decode(SubscriptionsResponse.self, from: data)
            return response.subscriptions
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
    // MARK: - Usage Monitor
    
    func fetchUsage() async -> UsageData? {
        do {
            let url = URL(string: "\(baseURL)/usage")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(UsageData.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
    // MARK: - AI Markup Tool
    
    func generateMarkup(projectName: String, description: String, rooms: [String]) async -> CommandResult? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/markup/generate")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            
            let body: [String: Any] = [
                "project_name": projectName,
                "description": description,
                "rooms": rooms
            ]
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(CommandResult.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
    // MARK: - Leads
    
    func runCommand(_ endpoint: String) async -> CommandResult? {
        return await runCommandInternal(endpoint: endpoint)
    }
    
    // MARK: - Social / X (same as Telegram SEO menu)
    
    func socialStory() async -> CommandResult? { await runCommand("/social/story") }
    func socialTip() async -> CommandResult? { await runCommand("/social/tip") }
    func socialVideo() async -> CommandResult? { await runCommand("/social/video") }
    func socialWeek() async -> CommandResult? { await runCommand("/social/week") }
    func socialXQueue() async -> CommandResult? { await runCommand("/social/x-queue") }
    func socialXPost() async -> CommandResult? { await runCommand("/social/x-post") }
    func socialXUsage() async -> CommandResult? { await runCommand("/social/x-usage") }
    
    // MARK: - SEO (same as Telegram)
    
    func seoKeywords() async -> CommandResult? { await runCommand("/seo/keywords") }
    func seoContent() async -> CommandResult? { await runCommand("/seo/content") }
    func seoLocal() async -> CommandResult? { await runCommand("/seo/local") }
    
    // MARK: - Facts (cortex ingest)
    
    func submitFacts(text: String, category: String, learnNow: Bool = false) async -> FactsLearnResult? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/facts/learn")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: Any] = [
                "text": text,
                "category": category,
                "learn_now": learnNow
            ]
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(FactsLearnResult.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
    func fetchFactCategories() async -> [String] {
        do {
            let url = URL(string: "\(baseURL)/facts/categories")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let response = try JSONDecoder().decode(FactsCategoriesResponse.self, from: data)
            return response.categories
        } catch {
            return ["control4", "lutron", "audio", "video", "networking", "general"]
        }
    }

    func runCurator(limit: Int = 0, force: Bool = false, contains: String? = nil) async -> CuratorRunResult? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/cortex/curator/run")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            var body: [String: Any] = [
                "limit": limit,
                "force": force
            ]
            if let contains, !contains.isEmpty {
                body["contains"] = contains
            }
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(CuratorRunResult.self, from: data)
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
            return nil
        }
    }

    func fetchCuratorStatus() async -> CuratorStatusResponse? {
        do {
            let url = URL(string: "\(baseURL)/cortex/curator/status")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(CuratorStatusResponse.self, from: data)
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
            return nil
        }
    }

    func fetchCuratorReview(
        status: String = "review",
        limit: Int = 30,
        offset: Int = 0,
        minConfidence: Double = -1.0,
        minProfessional: Double = 0.25,
        subject: String = ""
    ) async -> CuratorReviewResponse? {
        do {
            var comps = URLComponents(string: "\(baseURL)/cortex/curator/review")!
            comps.queryItems = [
                URLQueryItem(name: "status", value: status),
                URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "offset", value: String(offset)),
                URLQueryItem(name: "min_confidence", value: String(minConfidence)),
                URLQueryItem(name: "min_professional", value: String(minProfessional)),
                URLQueryItem(name: "subject", value: subject),
            ]
            guard let url = comps.url else { return nil }
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(CuratorReviewResponse.self, from: data)
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
            return nil
        }
    }

    func promoteCuratorFacts(ids: [Int]) async -> CuratorActionResponse? {
        await setCuratorFactStatus(ids: ids, endpoint: "/cortex/curator/promote")
    }

    func demoteCuratorFacts(ids: [Int]) async -> CuratorActionResponse? {
        await setCuratorFactStatus(ids: ids, endpoint: "/cortex/curator/demote")
    }

    func fetchMemoryGuardStatus() async -> MemoryGuardStatusResponse? {
        do {
            let url = URL(string: "\(baseURL)/memory_guard/status")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(MemoryGuardStatusResponse.self, from: data)
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
            return nil
        }
    }
    
    // MARK: - Claude Approval (Bridge: Task Board → iOS → Bob)
    
    func fetchClaudePendingTasks() async -> [ClaudeTask] {
        do {
            let url = URL(string: "\(baseURL)/tasks/claude_pending")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let response = try JSONDecoder().decode(ClaudePendingResponse.self, from: data)
            return response.tasks
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return []
        }
    }
    
    func approveClaudeTask(id: Int) async -> (success: Bool, message: String) {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/tasks/\(id)/approve_claude")!)
            request.httpMethod = "POST"
            let (data, _) = try await URLSession.shared.data(for: request)
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                let success = json["success"] as? Bool ?? false
                let message = json["message"] as? String ?? "Unknown response"
                return (success, message)
            }
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return (false, error.localizedDescription)
        }
        return (false, "Unknown error")
    }
    
    func fetchClaudeWorkflows() async -> [ClaudeWorkflow] {
        do {
            let url = URL(string: "\(baseURL)/claude/workflows")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let response = try JSONDecoder().decode(ClaudeWorkflowsResponse.self, from: data)
            return response.workflows
        } catch {
            return []
        }
    }
    
    // MARK: - Local AI (Ollama)
    
    func checkOllama() async {
        do {
            let url = URL(string: "\(ollamaURL)/api/tags")!
            var request = URLRequest(url: url)
            request.timeoutInterval = 5
            let (_, response) = try await URLSession.shared.data(for: request)
            if let httpResponse = response as? HTTPURLResponse {
                await MainActor.run {
                    self.ollamaAvailable = httpResponse.statusCode == 200
                }
            }
        } catch {
            await MainActor.run {
                self.ollamaAvailable = false
            }
        }
    }
    
    func checkLMStudio() async {
        do {
            let url = URL(string: "\(lmStudioURL)/v1/models")!
            var request = URLRequest(url: url)
            request.timeoutInterval = 5
            let (_, response) = try await URLSession.shared.data(for: request)
            if let httpResponse = response as? HTTPURLResponse {
                await MainActor.run {
                    self.lmStudioAvailable = httpResponse.statusCode == 200
                }
            }
        } catch {
            await MainActor.run {
                self.lmStudioAvailable = false
            }
        }
    }
    
    func fetchAIStatus() async {
        do {
            let url = URL(string: "\(baseURL)/ai/status")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let status = try JSONDecoder().decode(AIBackendStatus.self, from: data)
            await MainActor.run {
                self.aiBackendStatus = status
                self.ollamaAvailable = self.ollamaAvailable || status.ollama
                self.lmStudioAvailable = self.lmStudioAvailable || status.lm_studio
            }
        } catch {
            await MainActor.run {
                self.aiBackendStatus = nil
            }
        }
    }

    func verifyOllama() async -> (ok: Bool, message: String) {
        do {
            let url = URL(string: "\(baseURL)/ai/verify/ollama")!
            var request = URLRequest(url: url)
            request.timeoutInterval = 10
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode == 404 {
                return (false, "Verify endpoint not found — restart Mobile API")
            }
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let ok = json["ok"] as? Bool, let msg = json["message"] as? String {
                    await fetchAIStatus()
                    return (ok, msg)
                }
                if let detail = json["detail"] as? String { return (false, detail) }
                if let err = json["error"] as? String { return (false, err) }
            }
        } catch {
            return (false, error.localizedDescription)
        }
        return (false, "Invalid response — restart Mobile API")
    }

    func verifyLMStudio() async -> (ok: Bool, message: String) {
        do {
            let url = URL(string: "\(baseURL)/ai/verify/lm_studio")!
            var request = URLRequest(url: url)
            request.timeoutInterval = 10
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode == 404 {
                return (false, "Verify endpoint not found — restart Mobile API")
            }
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let ok = json["ok"] as? Bool, let msg = json["message"] as? String {
                    await fetchAIStatus()
                    return (ok, msg)
                }
                if let detail = json["detail"] as? String { return (false, detail) }
                if let err = json["error"] as? String { return (false, err) }
            }
        } catch {
            return (false, error.localizedDescription)
        }
        return (false, "Invalid response — restart Mobile API")
    }

    func askAI(question: String, source: String? = nil) async -> (answer: String?, source: String) {
        // Server handles smart routing. Pass source to force: auto, cortex, ollama, lm_studio, gpt-4o-mini, perplexity
        
        do {
            let url = URL(string: "\(baseURL)/ai/chat")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 120
            
            var body: [String: String] = ["question": question]
            let src = source ?? preferredAISource
            if src != "auto" {
                body["source"] = src
            }
            request.httpBody = try JSONEncoder().encode(body)
            
            let (data, _) = try await URLSession.shared.data(for: request)
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                let output = json["output"] as? String
                let source = json["source"] as? String ?? "unknown"
                return (output, source)
            }
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
        }
        return (nil, "error")
    }
    
    // MARK: - Helpers
    
    private func runCommandInternal(endpoint: String) async -> CommandResult? {
        do {
            let url = URL(string: "\(baseURL)\(endpoint)")!
            var request = URLRequest(url: url)
            request.timeoutInterval = 120 // Long timeout for scans
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(CommandResult.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
    private func postCommand(endpoint: String, body: [String: String]) async -> CommandResult? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)\(endpoint)")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
            
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(CommandResult.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    private func setCuratorFactStatus(ids: [Int], endpoint: String) async -> CuratorActionResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)\(endpoint)")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: Any] = ["fact_ids": ids, "status": "review"]
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(CuratorActionResponse.self, from: data)
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
            return nil
        }
    }
}

// MARK: - Models

struct DashboardResponse: Codable {
    let stats: DashboardStats
    let services: [ServiceStatus]
    let timestamp: String
}

struct DashboardStats: Codable {
    let bids: BidStats
    let proposals: ProposalStats
    let invoices: InvoiceStats
    let cortex: CortexStats
    let subscriptions: SubscriptionStats
    
    struct BidStats: Codable {
        let new: Int
        let pending: Int
    }
    
    struct ProposalStats: Codable {
        let draft: Int
        let sent: Int
        let accepted: Int
    }
    
    struct InvoiceStats: Codable {
        let pending: Int
        let overdue: Int
        let paid_this_month: Int
    }
    
    struct CortexStats: Codable {
        let articles: Int
        let size_kb: Double
    }
    
    struct SubscriptionStats: Codable {
        let monthly_total: Double
        let count: Int
    }
}

struct ServicesResponse: Codable {
    let services: [ServiceStatus]
}

struct ServiceStatus: Codable, Identifiable {
    var id: String { key }
    let name: String
    let key: String
    let status: String
    let port: Int?
    let url: String?
    let type: String?
    
    var isRunning: Bool {
        status == "running" || status == "loaded"
    }
}

struct CommandResult: Codable {
    let success: Bool
    let output: String?
    let error: String?
}

struct FactsLearnResult: Codable {
    let success: Bool
    let path: String?
    let category: String?
    let chars: Int?
    let learned: Bool?
    let error: String?
}

struct FactsCategoriesResponse: Codable {
    let categories: [String]
}

struct CuratorRunResult: Codable {
    let success: Bool
    let indexed_files: Int?
    let new_facts: Int?
    let updated_facts: Int?
    let trusted_facts: Int?
    let review_facts: Int?
    let contradiction_pairs: Int?
    let error: String?
}

struct CuratorStatusResponse: Codable {
    let success: Bool
    let total_facts: Int
    let trusted_facts: Int
    let review_facts: Int
    let contradiction_pairs: Int
    let last_indexed: String?
    let review_queue: [CuratorQueueItem]
}

struct CuratorReviewResponse: Codable {
    let success: Bool
    let status_filter: String
    let total: Int
    let limit: Int
    let offset: Int
    let items: [CuratorQueueItem]
}

struct CuratorQueueItem: Codable, Identifiable, Hashable {
    let id: Int
    let fact: String
    let subject: String?
    let confidence: Double
    let source_count: Int
    let contradictions: Int
    let domain_score: Double
    let reasoning_score: Double
    let troubleshooting_score: Double
    let professional_score: Double?
    let status: String?
    let last_seen: String?
}

struct CuratorActionResponse: Codable {
    let success: Bool
    let updated: Int?
    let missing_ids: [Int]?
    let status_set_to: String?
    let error: String?
}

struct MemoryGuardStatusResponse: Codable {
    let success: Bool
    let timestamp: String
    let job: MemoryGuardJobStatus
}

struct MemoryGuardJobStatus: Codable {
    let label: String
    let loaded: Bool
    let running: Bool
    let pid: Int?
    let last_exit_code: Int?
    let plist_exists: Bool
    let plist_path: String?
    let error: String?
}

struct ProposalsResponse: Codable {
    let proposals: [Proposal]
}

struct Proposal: Codable, Identifiable {
    let id: String
    let client: String
    let status: String
    let total: Double
    let created: String
}

struct SubscriptionsResponse: Codable {
    let subscriptions: [Subscription]
}

struct Subscription: Codable, Identifiable {
    var id: String { name }
    let name: String
    let category: String
    let cost: Double
    let billing_cycle: String
    let usage: String?
}

struct WebsiteStatus: Codable {
    let timestamp: String
    let sites: [String: SiteStatus]
    
    struct SiteStatus: Codable {
        let url: String
        let uptime: UptimeStatus
        let ssl: SSLStatus
        
        struct UptimeStatus: Codable {
            let status: String
            let response_time_s: Double?
        }
        
        struct SSLStatus: Codable {
            let status: String
            let days_until_expiry: Int?
        }
    }
}

// MARK: - Usage Models

struct UsageData: Codable {
    let timestamp: String
    let services: [ServiceUsage]
    let subscriptions: SubscriptionSummary
    
    struct SubscriptionSummary: Codable {
        let monthly_total: Double
        let count: Int
    }
}

struct ServiceUsage: Codable {
    let service: String
    let cost: Double
    let used: Double
    let limit: Double
    let unit: String
    let pct: Double
    let status: String
    let reset_date: String?
    let last_updated: String?
    let api_pct: Double?
}

// MARK: - Claude Approval Models

struct ClaudePendingResponse: Codable {
    let tasks: [ClaudeTask]
    let error: String?
}

struct ClaudeTask: Codable, Identifiable {
    let id: Int
    let title: String
    let description: String
    let priority: String
    let created_at: String
}

struct ClaudeWorkflowsResponse: Codable {
    let workflows: [ClaudeWorkflow]
    let error: String?
}

struct ClaudeWorkflow: Codable, Identifiable {
    let id: String
    let title: String
    let prompt: String
}

struct AIBackendStatus: Codable {
    let cortex: Bool
    let ollama: Bool
    let lm_studio: Bool
    let openai: Bool
    let perplexity: Bool
}
