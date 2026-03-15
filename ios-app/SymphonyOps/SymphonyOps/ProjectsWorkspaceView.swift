import SwiftUI
import UniformTypeIdentifiers
import UIKit

struct ProjectsWorkspaceView: View {
    @EnvironmentObject var api: APIClient
    var mode: ProjectsWorkspaceMode = .sow
    @State private var proposalScopeProjectName = ""
    @State private var proposalScopeClientName = ""
    @State private var proposalScopeRunAI = true
    @State private var showProposalScopeImporter = false
    @State private var selectedProposalScopeFile: URL?
    @State private var proposalScopeResponse: ProposalScopeResponse?
    @State private var sowShareURL: URL?
    @State private var showSOWShareSheet = false
    @State private var manualDigestProjectName = ""
    @State private var manualDigestRunAI = true
    @State private var showManualDigestImporter = false
    @State private var selectedManualDigestFiles: [URL] = []
    @State private var manualDigestResponse: ProjectManualDigestResponse?
    @State private var roomModelerProjectName = ""
    @State private var roomModelerSystemProfile = "control4"
    @State private var showRoomModelerImporter = false
    @State private var selectedRoomModelerFile: URL?
    @State private var roomModelerResponse: RoomModelerResponse?
    @State private var isLoading = false
    @State private var resultMessage: String?

    var markupURL: URL {
        api.markupURL ?? api.fallbackMarkupURL
    }

    var body: some View {
        List {
            if mode == .markup {
                Section("Markup") {
                    Link(destination: markupURL) {
                        Label("Open Markup Tool", systemImage: "pencil.and.outline")
                    }
                }
            }

            if mode == .sow {
                Section("SOW Generator") {
                Text("Upload a finished proposal to generate scope, inclusions, exclusions, assumptions, and risk tags.")
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
                ) { pickerResult in
                    showProposalScopeImporter = false
                    switch pickerResult {
                    case .success(let urls):
                        selectedProposalScopeFile = urls.first
                    case .failure(let err):
                        self.resultMessage = "Proposal Scope picker failed: \(err.localizedDescription)"
                    }
                }

                Toggle("Run AI summary", isOn: $proposalScopeRunAI)

                Button {
                    Task { await runProposalScopeAgent() }
                } label: {
                    Label("Generate Scope of Work", systemImage: "doc.badge.gearshape")
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading || selectedProposalScopeFile == nil)
            }

                if let proposalScope = proposalScopeResponse {
                    Section("Latest SOW Output") {
                        if let quote = proposalScope.dtools_quote_version, !quote.isEmpty {
                            Text("D-Tools: \(quote)")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        if let scope = proposalScope.scope {
                            if let lines = scope.scope_of_work, !lines.isEmpty {
                                resultBlock("Scope of Work", items: Array(lines.prefix(10)))
                            }
                            if let included = scope.included_items, !included.isEmpty {
                                resultBlock("Included", items: Array(included.prefix(10)))
                            }
                            if let excluded = scope.excluded_items, !excluded.isEmpty {
                                resultBlock("Excluded", items: Array(excluded.prefix(8)))
                            }
                            if let assumptions = scope.assumptions, !assumptions.isEmpty {
                                resultBlock("Assumptions", items: Array(assumptions.prefix(8)))
                            }
                            if let risks = scope.risk_tags, !risks.isEmpty {
                                Text("Risk Tags: \(risks.joined(separator: ", "))")
                                    .font(.caption2)
                                    .foregroundColor(.orange)
                            }
                        }

                        Button {
                            exportProposalScopeMarkdown()
                        } label: {
                            Label("Export SOW Markdown", systemImage: "square.and.arrow.up")
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }

            if mode == .manualDigest {
                Section("New Project Manual Digest") {
                    TextField("Project name", text: $manualDigestProjectName)
                        .textFieldStyle(.roundedBorder)

                    Button {
                        showManualDigestImporter = true
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
                        switch result {
                        case .success(let urls):
                            selectedManualDigestFiles = urls
                        case .failure(let err):
                            resultMessage = "Manual digest picker failed: \(err.localizedDescription)"
                        }
                    }

                    Toggle("Run AI summary", isOn: $manualDigestRunAI)

                    Button {
                        Task { await runManualDigest() }
                    } label: {
                        Label("Run Manual Digest", systemImage: "brain.head.profile")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading || selectedManualDigestFiles.isEmpty)
                }

                if let digest = manualDigestResponse {
                    Section("Latest Manual Digest") {
                        Text("Project: \(digest.project_name ?? manualDigestProjectName)")
                            .font(.caption)
                        if let brands = digest.digest?.detected_brands, !brands.isEmpty {
                            resultBlock("Detected Brands", items: Array(brands.prefix(10)))
                        }
                        if let skus = digest.digest?.detected_skus, !skus.isEmpty {
                            resultBlock("Detected SKUs", items: Array(skus.prefix(10)))
                        }
                    }
                }
            }

            if mode == .roomModeler {
                Section("Room Modeler") {
                    Text("Upload a .symphony markup and generate a per-room implementation model.")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    TextField("Project name", text: $roomModelerProjectName)
                        .textFieldStyle(.roundedBorder)

                    Picker("System", selection: $roomModelerSystemProfile) {
                        Text("Control4").tag("control4")
                        Text("Lutron").tag("lutron")
                        Text("Sonos").tag("sonos")
                        Text("Hybrid").tag("hybrid")
                    }
                    .pickerStyle(.menu)

                    Button {
                        showRoomModelerImporter = true
                    } label: {
                        HStack {
                            Image(systemName: "square.and.arrow.down.on.square")
                            Text(selectedRoomModelerFile == nil ? "Choose .symphony File" : selectedRoomModelerFile!.lastPathComponent)
                                .lineLimit(1)
                        }
                    }
                    .buttonStyle(.bordered)
                    .fileImporter(
                        isPresented: $showRoomModelerImporter,
                        allowedContentTypes: [.json, .data],
                        allowsMultipleSelection: false
                    ) { result in
                        switch result {
                        case .success(let urls):
                            selectedRoomModelerFile = urls.first
                        case .failure(let err):
                            resultMessage = "Room modeler picker failed: \(err.localizedDescription)"
                        }
                    }

                    Button {
                        Task { await runRoomModeler() }
                    } label: {
                        Label("Generate Room Model", systemImage: "building.2.crop.circle")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading || selectedRoomModelerFile == nil)
                }

                if let model = roomModelerResponse, model.success {
                    Section("Generated Room Model") {
                        Text("Rooms: \(model.rooms_count ?? 0)")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        if let summary = model.summary {
                            Text("High priority: \(summary.high_priority_rooms ?? 0) • Symbols: \(summary.total_detected_symbols ?? 0)")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        ForEach(Array((model.rooms ?? []).prefix(20))) { room in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(room.room)
                                    .font(.subheadline)
                                    .fontWeight(.semibold)
                                Text("Priority: \((room.priority ?? "medium").capitalized) • Symbols: \(room.detected_symbols ?? 0)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                if let scope = room.recommended_scope, !scope.isEmpty {
                                    ForEach(Array(scope.prefix(2).enumerated()), id: \.offset) { _, line in
                                        Text("• \(line)")
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                    }
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }
            }
        }
        .navigationTitle("Projects")
        .overlay(alignment: .bottom) {
            if isLoading {
                ProgressView("Generating SOW...")
                    .padding(12)
                    .background(.thinMaterial, in: Capsule())
                    .padding()
            }
        }
        .alert("Status", isPresented: Binding<Bool>(
            get: { resultMessage != nil },
            set: { if !$0 { resultMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(resultMessage ?? "")
        }
        .sheet(isPresented: $showSOWShareSheet) {
            if let fileURL = sowShareURL {
                ActivityView(activityItems: [fileURL])
            }
        }
    }

    @ViewBuilder
    private func resultBlock(_ title: String, items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .fontWeight(.semibold)
            ForEach(Array(items.enumerated()), id: \.offset) { _, line in
                Text("• \(line)")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    @MainActor
    private func runProposalScopeAgent() async {
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
        if response?.success == true {
            resultMessage = "Scope generated."
        } else {
            resultMessage = response?.error ?? api.error ?? "Proposal scope agent failed"
        }
    }

    @MainActor
    private func runManualDigest() async {
        guard !selectedManualDigestFiles.isEmpty else { return }
        isLoading = true
        defer { isLoading = false }

        let response = await api.runProjectManualDigest(
            projectName: manualDigestProjectName.trimmingCharacters(in: .whitespacesAndNewlines),
            fileURLs: selectedManualDigestFiles,
            runAISummary: manualDigestRunAI
        )
        manualDigestResponse = response
        if response?.success == true {
            resultMessage = "Manual digest completed."
        } else {
            resultMessage = response?.error ?? api.error ?? "Manual digest failed"
        }
    }

    @MainActor
    private func runRoomModeler() async {
        guard let roomFile = selectedRoomModelerFile else { return }
        isLoading = true
        defer { isLoading = false }
        let response = await api.runRoomModeler(
            projectName: roomModelerProjectName.trimmingCharacters(in: .whitespacesAndNewlines),
            systemProfile: roomModelerSystemProfile,
            markupFileURL: roomFile
        )
        roomModelerResponse = response
        if response?.success == true {
            resultMessage = "Room model generated."
        } else {
            resultMessage = response?.error ?? api.error ?? "Room modeler failed"
        }
    }

    private func exportProposalScopeMarkdown() {
        guard let proposalScope = proposalScopeResponse else {
            resultMessage = "Generate a scope first, then export."
            return
        }
        let content = buildProposalScopeMarkdown(from: proposalScope)
        let slug = (proposalScope.project_slug?.isEmpty == false ? proposalScope.project_slug! : "proposal-scope")
        let timestamp = proposalScope.batch_timestamp ?? String(Int(Date().timeIntervalSince1970))
        let filename = "\(slug)_SOW_\(timestamp).md"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)

        do {
            try content.write(to: url, atomically: true, encoding: .utf8)
            sowShareURL = url
            showSOWShareSheet = true
        } catch {
            resultMessage = "Export failed: \(error.localizedDescription)"
        }
    }

    private func buildProposalScopeMarkdown(from response: ProposalScopeResponse) -> String {
        var lines: [String] = []
        lines.append("# Scope of Work")
        lines.append("")
        lines.append("- Project: \(response.project_name ?? "N/A")")
        lines.append("- Client: \(response.client_name ?? "N/A")")
        if let quote = response.dtools_quote_version, !quote.isEmpty {
            lines.append("- D-Tools Quote: \(quote)")
        }
        lines.append("")

        func appendSection(_ title: String, _ items: [String]?) {
            guard let items, !items.isEmpty else { return }
            lines.append("## \(title)")
            for item in items {
                lines.append("- \(item)")
            }
            lines.append("")
        }

        let scope = response.scope
        appendSection("Scope of Work", scope?.scope_of_work)
        appendSection("Included", scope?.included_items)
        appendSection("Excluded", scope?.excluded_items)
        appendSection("Assumptions", scope?.assumptions)
        appendSection("Allowances", scope?.allowances)
        appendSection("Schedule Notes", scope?.schedule_notes)
        appendSection("Open Questions", scope?.open_questions)

        if let riskTags = scope?.risk_tags, !riskTags.isEmpty {
            lines.append("## Risk Tags")
            lines.append(riskTags.map { "`\($0)`" }.joined(separator: ", "))
            lines.append("")
        }
        if let ai = response.ai_summary {
            appendSection("AI Key Findings", ai.key_findings)
            appendSection("AI Recommended Devices", ai.recommended_devices)
            appendSection("AI Risks", ai.risks)
            appendSection("AI Clarifying Questions", ai.clarifying_questions)
            appendSection("AI Next Steps", ai.next_steps)
        }
        return lines.joined(separator: "\n")
    }
}
