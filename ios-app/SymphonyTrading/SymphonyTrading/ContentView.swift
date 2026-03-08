import SwiftUI

struct ContentView: View {
    @EnvironmentObject var api: TradingAPIClient
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            TradingMainView()
                .tabItem {
                    Label("Main", systemImage: "chart.line.uptrend.xyaxis")
                }
                .tag(0)

            ScanResearchView()
                .tabItem {
                    Label("Scan & Research", systemImage: "magnifyingglass")
                }
                .badge(api.highPriorityFlagCount > 0 ? api.highPriorityFlagCount : nil)
                .tag(1)
        }
    }
}

struct TradingMainView: View {
    @EnvironmentObject var api: TradingAPIClient

    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Trading API")) {
                    HStack {
                        Circle()
                            .fill(api.isConnected ? Color.green : Color.red)
                            .frame(width: 10, height: 10)
                        Text(api.isConnected ? "Connected" : "Disconnected")
                        Spacer()
                        Button("Refresh") {
                            Task { await api.refreshDashboard() }
                        }
                    }
                }

                Section(header: Text("Portfolio")) {
                    if let p = api.portfolio {
                        HStack {
                            Text("Portfolio Value")
                            Spacer()
                            Text("$\(String(format: "%.2f", p.current_value ?? 0))")
                        }
                        HStack {
                            Text("Cash")
                            Spacer()
                            Text("$\(String(format: "%.2f", p.cash ?? 0))")
                        }
                    } else {
                        Text("No portfolio data")
                            .foregroundColor(.secondary)
                    }
                }

                Section(header: Text("Goal")) {
                    if let g = api.goal {
                        Text(g.goal)
                        ProgressView(value: g.current_amount, total: max(g.target_amount, 1))
                        Text("$\(String(format: "%.2f", g.current_amount)) / $\(String(format: "%.2f", g.target_amount))")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    } else {
                        Text("No goal data")
                            .foregroundColor(.secondary)
                    }
                }

                Section(header: Text("Trading Memory")) {
                    if let m = api.memoryStatus {
                        Text("Scope: \(m.scope)")
                        Text("Facts \(m.total_facts) • Trusted \(m.trusted_facts) • Review \(m.review_facts)")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    } else {
                        Text("No memory status")
                            .foregroundColor(.secondary)
                    }
                }

                Section(header: Text("Automation Health")) {
                    if api.automationHealth.isEmpty {
                        Text("No automation health data yet")
                            .foregroundColor(.secondary)
                    } else {
                        ForEach(api.automationHealth) { item in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Circle()
                                        .fill(item.running ? Color.green : (item.loaded ? Color.orange : Color.red))
                                        .frame(width: 8, height: 8)
                                    Text(item.name)
                                    Spacer()
                                    Text(item.running ? "Running" : (item.loaded ? "Loaded" : "Not Loaded"))
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                                if let line = item.lastLogLine, !line.isEmpty {
                                    Text(line)
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                } else {
                                    Text("No recent log output")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }

                if let err = api.error {
                    Section(header: Text("Error")) {
                        Text(err)
                            .foregroundColor(.red)
                    }
                }
            }
            .navigationTitle("Symphony Trading")
            .task { await api.refreshDashboard() }
        }
    }
}

struct ScanResearchView: View {
    @EnvironmentObject var api: TradingAPIClient
    @State private var researchQuery = ""

    private func runResearchBot() {
        let input = researchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        let topics = input.isEmpty
            ? ["bitcoin", "ethereum", "polymarket", "fed rates", "ai stocks"]
            : input.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
        Task { await api.runResearchBot(topics: topics, maxTopics: 5) }
    }

    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Scan & Research")) {
                    Button("Run Market Scan") {
                        Task { await api.scanInvestments() }
                    }
                    HStack {
                        TextField("Research topic", text: $researchQuery)
                        Button("Go") {
                            let q = researchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
                            guard !q.isEmpty else { return }
                            Task { await api.research(query: q) }
                        }
                    }
                    Button("Run Research Bot (watch flags)") {
                        runResearchBot()
                    }
                }

                Section(header: Text("Scan Output")) {
                    if !api.scanOutput.isEmpty {
                        Text(api.scanOutput)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    } else {
                        Text("No scan or research output yet")
                            .foregroundColor(.secondary)
                    }
                }

                Section(header: Text("Provider Telemetry")) {
                    if let t = api.researchTelemetry {
                        HStack {
                            Text("Provider")
                            Spacer()
                            Text((t.provider ?? "unknown").uppercased())
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        HStack {
                            Text("Model")
                            Spacer()
                            Text(t.model ?? "n/a")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        HStack {
                            Text("From Cache")
                            Spacer()
                            Text((t.fromCache ?? false) ? "Yes" : "No")
                                .font(.caption)
                                .foregroundColor((t.fromCache ?? false) ? .green : .secondary)
                        }
                        if let latency = t.latencyMs {
                            HStack {
                                Text("Latency")
                                Spacer()
                                Text("\(latency) ms")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                        }
                        if let reason = t.fallbackReason, !reason.isEmpty {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Fallback Reason")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                                Text(reason)
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                        }
                        if let usage = t.usage {
                            Text("Budget \(usage.todayUsed ?? 0)/\(usage.dailyBudget ?? 0) today • \(usage.monthlyUsed ?? 0)/\(usage.monthlyLimit ?? 0) monthly")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                    } else {
                        Text("No research telemetry yet")
                            .foregroundColor(.secondary)
                    }
                }

                if let err = api.error {
                    Section(header: Text("Error")) {
                        Text(err)
                            .foregroundColor(.red)
                    }
                }
            }
            .navigationTitle("Scan & Research")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        runResearchBot()
                    } label: {
                        Label("Run Bot", systemImage: "bolt.fill")
                    }
                }
            }
            .task {
                if api.scanOutput.isEmpty {
                    await api.scanInvestments()
                }
            }
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
            .environmentObject(TradingAPIClient())
    }
}
