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
        async let c = checkConnection()
        async let p = fetchPortfolio()
        async let g = fetchGoal()
        async let m = fetchMemoryStatus()
        _ = await (c, p, g, m)
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
            await MainActor.run { self.scanOutput = result.output ?? result.error ?? "No output" }
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
            let result = try JSONDecoder().decode(CommandResult.self, from: data)
            await MainActor.run { self.scanOutput = result.output ?? result.error ?? "No output" }
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
}

struct CommandResult: Codable {
    let success: Bool
    let output: String?
    let error: String?
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
