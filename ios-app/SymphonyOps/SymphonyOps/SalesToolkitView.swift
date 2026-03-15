import SwiftUI
import UniformTypeIdentifiers

struct SalesToolkitView: View {
    @EnvironmentObject var api: APIClient
    var mode: SalesWorkspaceMode = .pipeline
    @State private var showProductImporter = false
    @State private var selectedSheetURL: URL?
    @State private var dealerTier = "standard"
    @State private var maxProducts = 25
    @State private var parseProfile = "auto"
    @State private var dryRun = true
    @State private var isLoading = false
    @State private var importResult: DToolsProductImportResponse?
    @State private var resultMessage: String?

    var body: some View {
        List {
            if mode == .pipeline {
                Section("Sales Pipeline") {
                    NavigationLink {
                        LeadsView()
                    } label: {
                        Label("Lead Pipeline", systemImage: "person.3")
                    }
                    NavigationLink {
                        AIChatView()
                    } label: {
                        Label("Ask Bob for Sales Copy", systemImage: "bubble.left.and.bubble.right")
                    }
                }
            }

            if mode == .dtoolsAgent {
                Section("D-Tools Product Agent") {
                    Text("Upload invoice, PDF, CSV, or XLSX and parse products for D-Tools.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Button {
                        showProductImporter = true
                    } label: {
                        HStack {
                            Image(systemName: "doc.badge.plus")
                            Text(selectedSheetURL == nil ? "Choose Invoice/PDF/CSV/XLSX" : selectedSheetURL!.lastPathComponent)
                                .lineLimit(1)
                        }
                    }
                    .buttonStyle(.bordered)
                    .fileImporter(
                        isPresented: $showProductImporter,
                        allowedContentTypes: [.pdf, .commaSeparatedText, .spreadsheet, .plainText, .data],
                        allowsMultipleSelection: false
                    ) { result in
                        switch result {
                        case .success(let urls):
                            selectedSheetURL = urls.first
                        case .failure(let err):
                            resultMessage = "File picker failed: \(err.localizedDescription)"
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
                        Text("Invoice (Rexel)").tag("invoice_rexel")
                        Text("MSRP + Standard/Silver/Gold").tag("msrp_three_tiers")
                        Text("MSRP + Standard only").tag("msrp_standard_only")
                        Text("Minimal").tag("minimal")
                    }
                    .pickerStyle(.menu)

                    Stepper("Max Products: \(maxProducts)", value: $maxProducts, in: 1...250)
                    Toggle("Dry Run", isOn: $dryRun)

                    Button {
                        Task { await runProductImport() }
                    } label: {
                        Label("Run Product Agent", systemImage: "wand.and.stars")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading || selectedSheetURL == nil)
                }

                if let importResult {
                    Section("Latest Import Result") {
                        Text("Parsed: \(importResult.parsed_count ?? 0) • Created: \(importResult.created_count ?? 0)")
                            .font(.caption)
                        if let err = importResult.error, !err.isEmpty {
                            Text(err)
                                .font(.caption2)
                                .foregroundColor(.orange)
                        }
                    }
                }
            }
        }
        .navigationTitle("Sales")
        .alert("Status", isPresented: Binding<Bool>(
            get: { resultMessage != nil },
            set: { if !$0 { resultMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(resultMessage ?? "")
        }
    }

    @MainActor
    private func runProductImport() async {
        guard let selectedSheetURL else { return }
        isLoading = true
        defer { isLoading = false }

        let response = await api.importDToolsProducts(
            fileURL: selectedSheetURL,
            createInDTools: !dryRun,
            maxProducts: maxProducts,
            dealerTier: dealerTier,
            parseProfile: parseProfile,
            expectedColumns: [],
            dryRun: dryRun
        )
        importResult = response
        if response?.success == true {
            resultMessage = "D-Tools product agent completed."
        } else {
            resultMessage = response?.error ?? api.error ?? "D-Tools product agent failed"
        }
    }
}
