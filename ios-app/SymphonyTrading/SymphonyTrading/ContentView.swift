import SwiftUI

struct ContentView: View {
    @EnvironmentObject var api: TradingAPIClient
    @State private var researchQuery = ""

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
                    if !api.scanOutput.isEmpty {
                        Text(api.scanOutput)
                            .font(.caption)
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

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
            .environmentObject(TradingAPIClient())
    }
}
