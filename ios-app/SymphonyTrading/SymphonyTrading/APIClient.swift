import Foundation

extension UserDefaults {
    func containsTrading(key: String) -> Bool {
        return object(forKey: key) != nil
    }
}

class TradingAPIClient: ObservableObject {
    @Published var isConnected = false
    @Published var error: String?
    @Published var portfolio: PortfolioData?
    @Published var goal: GoalData?
    @Published var scanOutput: String = ""
    @Published var memoryStatus: TradingMemoryStatus?
    @Published var researchTelemetry: ResearchTelemetry?
    @Published var automationHealth: [AutomationHealthItem] = []
    @Published var highPriorityFlagCount: Int = 0

    var baseURL: String {
        UserDefaults.standard.string(forKey: "trading_api_base_url") ?? "http://bobs-mac-mini:8421"
    }

    func setBaseURL(_ url: String) {
        UserDefaults.standard.set(url, forKey: "trading_api_base_url")
    }

    func checkConnection() async {
        do {
            let url = URL(string: "\(baseURL)/health")!
            let (_, response) = try await URLSession.shared.data(from: url)
            await MainActor.run {
                self.isConnected = (response as? HTTPURLResponse)?.statusCode == 200
                self.error = nil
            }
        } catch {
            await MainActor.run {
                self.isConnected = false
                self.error = error.localizedDescription
            }
        }
    }

    func refreshDashboard() async {
        await checkConnection()
        await fetchPortfolio()
        await fetchGoal()
        await fetchMemoryStatus()
        await fetchAutomationHealth()
    }

    func fetchPortfolio() async {
        do {
            let url = URL(string: "\(baseURL)/portfolio")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let model = try JSONDecoder().decode(PortfolioData.self, from: data)
            await MainActor.run { self.portfolio = model }
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
        }
    }

    func fetchGoal() async {
        do {
            let url = URL(string: "\(baseURL)/portfolio/goal")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let model = try JSONDecoder().decode(GoalData.self, from: data)
            await MainActor.run { self.goal = model }
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
        }
    }

    func scanInvestments() async {
        do {
            let url = URL(string: "\(baseURL)/invest/scan")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let result = try JSONDecoder().decode(CommandResult.self, from: data)
            await MainActor.run {
                self.scanOutput = result.output ?? result.error ?? "No output"
                self.highPriorityFlagCount = parseHighPriorityFlagCount(from: self.scanOutput)
            }
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
        }
    }

    func research(query: String) async {
        do {
            var req = URLRequest(url: URL(string: "\(baseURL)/invest/research")!)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["query": query])
            let (data, _) = try await URLSession.shared.data(for: req)
            let result = try JSONDecoder().decode(ResearchCommandResult.self, from: data)
            await MainActor.run {
                self.scanOutput = result.output ?? result.error ?? "No output"
                self.researchTelemetry = result.telemetry
                self.highPriorityFlagCount = parseHighPriorityFlagCount(from: self.scanOutput)
            }
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
        }
    }

    func runResearchBot(topics: [String], maxTopics: Int = 5) async {
        do {
            var req = URLRequest(url: URL(string: "\(baseURL)/invest/research/bot")!)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let cleanTopics = topics.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            req.httpBody = try JSONSerialization.data(
                withJSONObject: [
                    "topics": cleanTopics,
                    "max_topics": maxTopics,
                    "curate_now": true
                ]
            )
            let (data, _) = try await URLSession.shared.data(for: req)
            let result = try JSONDecoder().decode(CommandResult.self, from: data)
            await MainActor.run {
                self.scanOutput = result.output ?? result.error ?? "No output"
                self.highPriorityFlagCount = parseHighPriorityFlagCount(from: self.scanOutput)
            }
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
        }
    }

    func fetchMemoryStatus() async {
        do {
            let url = URL(string: "\(baseURL)/memory/curator/status")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let model = try JSONDecoder().decode(TradingMemoryStatus.self, from: data)
            await MainActor.run { self.memoryStatus = model }
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
        }
    }

    func fetchAutomationHealth() async {
        do {
            let url = URL(string: "\(baseURL)/automation/health")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let model = try JSONDecoder().decode(AutomationHealthResponse.self, from: data)
            await MainActor.run { self.automationHealth = model.items }
        } catch {
            await MainActor.run { self.error = error.localizedDescription }
        }
    }

    private func parseHighPriorityFlagCount(from text: String) -> Int {
        let upper = text.uppercased()
        let patterns = [
            "HIGH PRIORITY",
            "HIGH-PRIORITY",
            "WATCH-WORTHY",
            "ALERT",
            "🚩"
        ]
        var count = 0
        for token in patterns {
            count += upper.components(separatedBy: token).count - 1
        }
        return max(0, count)
    }
}

struct CommandResult: Codable {
    let success: Bool
    let output: String?
    let error: String?
}

struct ResearchCommandResult: Codable {
    let success: Bool
    let output: String?
    let error: String?
    let telemetry: ResearchTelemetry?
}

struct ResearchTelemetry: Codable {
    let provider: String?
    let model: String?
    let fallbackReason: String?
    let fromCache: Bool?
    let latencyMs: Int?
    let usage: ResearchUsage?

    enum CodingKeys: String, CodingKey {
        case provider
        case model
        case fallbackReason = "fallback_reason"
        case fromCache = "from_cache"
        case latencyMs = "latency_ms"
        case usage
    }
}

struct ResearchUsage: Codable {
    let monthlyUsed: Int?
    let monthlyLimit: Int?
    let monthlyRemaining: Int?
    let dailyBudget: Int?
    let todayUsed: Int?
    let canQuery: Bool?

    enum CodingKeys: String, CodingKey {
        case monthlyUsed = "monthly_used"
        case monthlyLimit = "monthly_limit"
        case monthlyRemaining = "monthly_remaining"
        case dailyBudget = "daily_budget"
        case todayUsed = "today_used"
        case canQuery = "can_query"
    }
}

struct PortfolioData: Codable {
    let initial_capital: Double?
    let current_value: Double?
    let cash: Double?
}

struct GoalData: Codable {
    let goal: String
    let target_amount: Double
    let current_amount: Double
    let status: String?
}

struct TradingMemoryStatus: Codable {
    let success: Bool
    let scope: String
    let total_facts: Int
    let trusted_facts: Int
    let review_facts: Int
    let contradiction_pairs: Int
}

struct AutomationHealthResponse: Codable {
    let success: Bool
    let items: [AutomationHealthItem]
}

struct AutomationHealthItem: Codable, Identifiable {
    var id: String { key }
    let key: String
    let name: String
    let label: String
    let loaded: Bool
    let running: Bool
    let pid: Int?
    let lastExitCode: Int?
    let lastLogLine: String?

    enum CodingKeys: String, CodingKey {
        case key
        case name
        case label
        case loaded
        case running
        case pid
        case lastExitCode = "last_exit_code"
        case lastLogLine = "last_log_line"
    }
}
