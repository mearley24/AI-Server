import SwiftUI

struct OpsAutomationView: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    var mode: OpsWorkspaceMode = .health
    @State private var isLoading = false
    @State private var resultMessage: String?
    @State private var notesProcessTarget = ""
    @State private var opsHealth: OpsHealthResponse?
    @State private var incidentQueue: IncidentQueueResponse?
    @State private var notesPipelineStatus: NotesPipelineStatusResponse?
    @State private var contactsStatus: ContactsStatusResponse?
    @State private var recentTexts: [IMessageRecentItem] = []
    @State private var networkDropoutStatus: NetworkDropoutStatusResponse?
    @State private var incidentNote = ""
    @State private var control4IP = ""
    @State private var sonosIP = ""
    @AppStorage("weather.setup.enabled.v1") private var weatherSetupEnabled = false
    @AppStorage("weather.location.v1") private var weatherLocation = ""
    @AppStorage("weather.provider.v1") private var weatherProvider = "openweather"
    @AppStorage("weather.api_key_name.v1") private var weatherAPIKeyName = "OPENWEATHER_API_KEY"

    var body: some View {
        List {
            if mode == .health {
                Section("Automation Health") {
                actionButtons(
                    primaryTitle: "Run Recovery",
                    primaryIcon: "cross.case.fill",
                    primaryAction: { Task { await runOpsRecoveryNow() } },
                    secondaryTitle: "Refresh",
                    secondaryIcon: "arrow.clockwise",
                    secondaryAction: { Task { await refreshForMode() } }
                )

                if let health = opsHealth {
                    LabeledContent("Ops status", value: health.status.capitalized)
                        .font(.caption)
                    if let problems = health.problems, !problems.isEmpty {
                        Text("Problems: \(problems.prefix(3).joined(separator: " • "))")
                            .font(.caption2)
                            .foregroundColor(.orange)
                    }
                }
                if let queue = incidentQueue {
                    Text("Incident queue: \(queue.count)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }
            }

            if mode == .dropout {
                Section("Dropout Watch") {
                actionButtons(
                    primaryTitle: "Start Watcher",
                    primaryIcon: "play.circle.fill",
                    primaryAction: { Task { await startDropoutWatch() } },
                    secondaryTitle: "Stop Watcher",
                    secondaryIcon: "stop.circle",
                    secondaryAction: { Task { await stopDropoutWatch() } }
                )

                TextField("Control4 IP (optional)", text: $control4IP)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.numbersAndPunctuation)
                TextField("Sonos IP (optional)", text: $sonosIP)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.numbersAndPunctuation)

                if let watch = networkDropoutStatus {
                    LabeledContent("Watcher", value: watch.running ? "Running" : "Stopped")
                        .font(.caption)
                    if let health = watch.status?.health {
                        LabeledContent("Health", value: health.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.caption2)
                            .foregroundColor(health == "healthy" ? .green : .orange)
                    }
                    if let sample = watch.status?.sample {
                        ForEach(["gateway", "wan", "control4", "sonos"], id: \.self) { key in
                            if let target = sample[key], let ok = target.ok {
                                let host = target.host ?? "n/a"
                                let latency = target.latency_ms.map { String(format: "%.1fms", $0) } ?? "timeout"
                                Text("• \(key.uppercased()): \(host) \(ok ? "OK" : "DOWN") \(latency)")
                                    .font(.system(.caption2, design: .monospaced))
                                    .foregroundColor(ok ? .secondary : .red)
                            }
                        }
                    }
                    if let events = watch.recent_events, !events.isEmpty {
                        Text("Recent: \(events.prefix(2).compactMap { $0.event }.joined(separator: " • "))")
                            .font(.caption2)
                            .foregroundColor(.secondary)

                        TextField("Incident note (optional)", text: $incidentNote)
                            .textFieldStyle(.roundedBorder)

                        Button {
                            Task { await createIncidentFromLatestDropoutEvent() }
                        } label: {
                            Label("Create Incident from Latest Event", systemImage: "exclamationmark.triangle.fill")
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.orange)
                        .disabled(isLoading)
                    }
                }
            }
            }

            if mode == .notes {
                Section("Notes + Messaging") {
                TextField("Note ID or project hint", text: $notesProcessTarget)
                    .textFieldStyle(.roundedBorder)

                actionButtons(
                    primaryTitle: "Process Notes",
                    primaryIcon: "bolt.horizontal.circle",
                    primaryAction: { Task { await processNotesNow() } },
                    secondaryTitle: "Process Texts",
                    secondaryIcon: "bolt.badge.clock",
                    secondaryAction: { Task { await processTextsNow() } }
                )

                if let pipeline = notesPipelineStatus {
                    Text("Notes watcher running: \((pipeline.jobs?.notes_watcher?.running ?? false) ? "Yes" : "No")")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                if let contacts = contactsStatus?.contacts?.contacts_count {
                    Text("Contacts indexed: \(contacts)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                ForEach(recentTexts.prefix(4)) { item in
                    Text("• \(item.contact_name ?? item.handle ?? "Unknown"): \(item.text ?? "")")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                }
            }
            }

            if mode == .weather {
                Section("Weather Setup") {
                    Toggle("Enable weather in Today", isOn: $weatherSetupEnabled)

                    Picker("Provider", selection: $weatherProvider) {
                        Text("OpenWeather").tag("openweather")
                        Text("WeatherAPI").tag("weatherapi")
                        Text("Custom").tag("custom")
                    }
                    .pickerStyle(.menu)

                    TextField("Location (e.g., Vail, CO)", text: $weatherLocation)
                        .textFieldStyle(.roundedBorder)

                    TextField("Vault key name for weather API key", text: $weatherAPIKeyName)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled(true)
                        .textFieldStyle(.roundedBorder)

                    actionButtons(
                        primaryTitle: "Save Weather Setup",
                        primaryIcon: "square.and.arrow.down.fill",
                        primaryAction: {
                            resultMessage = "Weather setup saved. Today tab now uses this configuration."
                        },
                        secondaryTitle: "Clear Setup",
                        secondaryIcon: "trash",
                        secondaryAction: {
                            weatherSetupEnabled = false
                            weatherLocation = ""
                            weatherProvider = "openweather"
                            weatherAPIKeyName = "OPENWEATHER_API_KEY"
                            resultMessage = "Weather setup cleared."
                        }
                    )

                    Text("Tip: store provider API key in Vault, then enter that key name here for team reference.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }
        }
        .navigationTitle("Ops")
        .task(id: mode) { await refreshForMode() }
        .overlay(alignment: .bottom) {
            if isLoading {
                ProgressView("Running...")
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
    }

    @ViewBuilder
    private func actionButtons(
        primaryTitle: String,
        primaryIcon: String,
        primaryAction: @escaping () -> Void,
        secondaryTitle: String,
        secondaryIcon: String,
        secondaryAction: @escaping () -> Void
    ) -> some View {
        if horizontalSizeClass == .regular {
            HStack {
                Button(action: primaryAction) {
                    Label(primaryTitle, systemImage: primaryIcon)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading)

                Button(action: secondaryAction) {
                    Label(secondaryTitle, systemImage: secondaryIcon)
                }
                .buttonStyle(.bordered)
                .disabled(isLoading)
            }
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Button(action: primaryAction) {
                    Label(primaryTitle, systemImage: primaryIcon)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading)

                Button(action: secondaryAction) {
                    Label(secondaryTitle, systemImage: secondaryIcon)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)
                .disabled(isLoading)
            }
        }
    }

    @MainActor
    private func refreshForMode() async {
        switch mode {
        case .health:
            opsHealth = await api.fetchOpsHealth()
            incidentQueue = await api.fetchIncidentQueue(limit: 20)
        case .dropout:
            networkDropoutStatus = await api.fetchNetworkDropoutStatus()
        case .notes:
            notesPipelineStatus = await api.fetchNotesPipelineStatus()
            contactsStatus = await api.fetchContactsStatus()
            recentTexts = (await api.fetchRecentIMessageWork(limit: 10))?.items ?? []
        case .weather:
            break
        }
    }

    @MainActor
    private func runOpsRecoveryNow() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.runOpsRecovery(apply: true, threshold: 0.8)
        if let response {
            resultMessage = "Recovery complete. Detected: \(response.detected_count ?? 0), applied: \(response.applied_count ?? 0)."
        } else {
            resultMessage = api.error ?? "Recovery run failed."
        }
        await refreshForMode()
    }

    @MainActor
    private func processNotesNow() async {
        isLoading = true
        defer { isLoading = false }
        let trimmed = notesProcessTarget.trimmingCharacters(in: .whitespacesAndNewlines)
        let noteId = Int(trimmed)
        let response = await api.processNoteNow(
            noteID: noteId,
            projectName: noteId == nil && !trimmed.isEmpty ? trimmed : nil
        )
        if response?.success == true {
            resultMessage = "Notes processed."
        } else {
            resultMessage = api.error ?? "Notes processing failed."
        }
        await refreshForMode()
    }

    @MainActor
    private func processTextsNow() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.processIMessagesNow()
        if response?.success == true {
            resultMessage = "Texts processed. Tasks created: \(response?.tasks_created ?? 0)."
        } else {
            resultMessage = api.error ?? "Text processing failed."
        }
        await refreshForMode()
    }

    @MainActor
    private func startDropoutWatch() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.startNetworkDropoutWatch(
            gatewayIP: "192.168.1.1",
            wanIP: "1.1.1.1",
            control4IP: control4IP.trimmingCharacters(in: .whitespacesAndNewlines),
            sonosIP: sonosIP.trimmingCharacters(in: .whitespacesAndNewlines),
            intervalSec: 2.0
        )
        resultMessage = response?.message ?? api.error ?? "Could not start dropout watch."
        await refreshForMode()
    }

    @MainActor
    private func stopDropoutWatch() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.stopNetworkDropoutWatch()
        resultMessage = response?.message ?? api.error ?? "Could not stop dropout watch."
        await refreshForMode()
    }

    @MainActor
    private func createIncidentFromLatestDropoutEvent() async {
        guard let event = networkDropoutStatus?.recent_events?.first else {
            resultMessage = "No recent dropout event available."
            return
        }
        isLoading = true
        defer { isLoading = false }
        let response = await api.createIncidentFromDropout(
            event: event,
            notes: incidentNote,
            priority: "high"
        )
        if response?.success == true {
            if let taskId = response?.task_id {
                resultMessage = "Incident created: #\(taskId)"
            } else {
                resultMessage = response?.message ?? "Incident created."
            }
            incidentNote = ""
        } else {
            resultMessage = response?.error ?? api.error ?? "Could not create incident."
        }
        await refreshForMode()
    }
}
