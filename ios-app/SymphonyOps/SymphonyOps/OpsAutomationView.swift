import SwiftUI
#if canImport(UIKit)
import UIKit
#endif
import LocalAuthentication

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
    @State private var contactsList: [ContactListItem] = []
    @State private var clientContacts: [ClientContactRecord] = []
    @State private var iMessageWatchlist: [String] = []
    @State private var contactsSearch = ""
    @State private var newClientName = ""
    @State private var newClientPhone = ""
    @State private var newClientEmail = ""
    @State private var newClientNotes = ""
    @State private var recentTexts: [IMessageRecentItem] = []
    @State private var networkDropoutStatus: NetworkDropoutStatusResponse?
    @State private var inventorySummary: OpsInventorySummaryResponse?
    @State private var turnkeyStatus: OpsTurnkeyStatusResponse?
    @State private var iMessageAutomation: IMessageAutomationConfig?
    @State private var iMessageBackfillPreview: IMessageBackfillResponse?
    @State private var iMessageIntakeItems: [IMessageIntakeItem] = []
    @State private var iMessageIntakeFailures: [IMessageIntakeFailureItem] = []
    @State private var showRealBackfillConfirm = false
    @State private var pendingRealBackfillWeeks = 4
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

                Button {
                    Task { await refreshTurnkeyStatus() }
                } label: {
                    Label("Check Turnkey Readiness", systemImage: "checklist")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)
                .disabled(isLoading)

                Button {
                    Task { await generateIntegrationBrief() }
                } label: {
                    Label("Generate Unified Integration Brief", systemImage: "sparkles")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading)

                if let turnkey = turnkeyStatus {
                    Text("Turnkey status: \((turnkey.ready ?? false) ? "Ready" : "Needs setup")")
                        .font(.caption2)
                        .foregroundColor((turnkey.ready ?? false) ? .green : .orange)
                    if let missing = turnkey.missing_env, !missing.isEmpty {
                        Text("Missing keys: \(missing.joined(separator: ", "))")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
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
                if let automation = iMessageAutomation {
                    Text("Auto invoice drafts: \((automation.create_service_invoice_drafts ?? true) ? "On" : "Off")")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    Text("Auto appointment drafts: \((automation.create_appointment_drafts ?? true) ? "On" : "Off")")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                HStack {
                    Button("Toggle Invoice Drafts") {
                        Task { await toggleInvoiceDraftAutomation() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                    Button("Toggle Appointment Drafts") {
                        Task { await toggleAppointmentDraftAutomation() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                }
                HStack {
                    Button("Test 4 Weeks") {
                        Task { await testIMessageBackfill(weeks: 4) }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                    Button("Test 6 Weeks") {
                        Task { await testIMessageBackfill(weeks: 6) }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                    Button("Test 8 Weeks") {
                        Task { await testIMessageBackfill(weeks: 8) }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                }
                HStack {
                    Button("Run 4 Weeks") {
                        pendingRealBackfillWeeks = 4
                        showRealBackfillConfirm = true
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading)
                    Button("Run 6 Weeks") {
                        pendingRealBackfillWeeks = 6
                        showRealBackfillConfirm = true
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading)
                    Button("Run 8 Weeks") {
                        pendingRealBackfillWeeks = 8
                        showRealBackfillConfirm = true
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading)
                }
                if let backfill = iMessageBackfillPreview {
                    let runLabel = (backfill.dry_run ?? true) ? "dry run" : "real run"
                    Text(
                        "Backfill \(backfill.weeks ?? 0)w (\(runLabel)): " +
                        "seen \(backfill.messages_seen ?? 0), monitored \(backfill.messages_monitored ?? 0), " +
                        "tasks \(backfill.tasks_created ?? 0), invoices \(backfill.invoice_drafts_created ?? 0), " +
                        "appointments \(backfill.appointment_drafts_created ?? 0)"
                    )
                    .font(.caption2)
                    .foregroundColor(.secondary)
                }
                Divider()
                Text("iMessage Intake Queue")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Button("Refresh Intake Queue") {
                    Task { await refreshIMessageIntake() }
                }
                .buttonStyle(.bordered)
                .disabled(isLoading)
                if iMessageIntakeItems.isEmpty {
                    Text("No pending intake drafts.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                } else {
                    ForEach(iMessageIntakeItems.prefix(12)) { item in
                        VStack(alignment: .leading, spacing: 6) {
                            Text("\(item.kind.capitalized) · \(item.status.capitalized)")
                                .font(.caption)
                            Text(item.contact_name_masked ?? item.handle_masked ?? "Unknown")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            if let project = item.project_hint, !project.isEmpty {
                                Text("Project: \(project)")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                            Text(item.request_text_redacted ?? "")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                                .lineLimit(2)
                            HStack {
                                if item.kind == "invoice" {
                                    Button("Approve Invoice") {
                                        Task { await approveInvoiceIntake(item) }
                                    }
                                    .buttonStyle(.borderedProminent)
                                    .disabled(isLoading)
                                } else {
                                    Button("Create Calendar Event") {
                                        Task { await createCalendarFromIntake(item) }
                                    }
                                    .buttonStyle(.borderedProminent)
                                    .disabled(isLoading)
                                }
                                Button("Send Confirmation Text") {
                                    Task { await sendConfirmationForIntake(item) }
                                }
                                .buttonStyle(.bordered)
                                .disabled(isLoading)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
                if !iMessageIntakeFailures.isEmpty {
                    Divider()
                    Text("Intake Action Failures")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Button("Retry All Pending Failures") {
                        Task { await retryAllIntakeFailures() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading)
                    ForEach(iMessageIntakeFailures.prefix(8)) { failure in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(failure.kind ?? "unknown").capitalized · \(failure.action ?? "action")")
                                    .font(.caption2)
                                Text(failure.last_error ?? "Unknown error")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                    .lineLimit(2)
                            }
                            Spacer()
                            Button("Retry") {
                                Task { await retryIntakeFailure(failure.id) }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)
                        }
                    }
                }
                Divider()
                Text("Scan List Manager")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text("Scanner prioritizes scan-list contacts and also catches work-like messages by keyword signal.")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                HStack {
                    Button("Sync Contacts") {
                        Task { await syncAndRefreshContacts() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                    Button("Open Contacts App") {
                        openContactsApp()
                    }
                    .buttonStyle(.bordered)
                }
                Button("Seed Scan List from Existing Clients") {
                    Task { await seedScanListFromExistingClients() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading)
                TextField("Search contacts", text: $contactsSearch)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        Task { await refreshContactsData() }
                    }
                Button("Refresh Contact List") {
                    Task { await refreshContactsData() }
                }
                .buttonStyle(.bordered)
                .disabled(isLoading)
                ForEach(contactsList.prefix(25), id: \.id) { contact in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(contact.name)
                                .font(.caption)
                            Text((contact.phones + contact.emails).joined(separator: " • "))
                                .font(.caption2)
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                        }
                        Spacer()
                        Button(isContactMonitored(contact) ? "Monitored" : "Monitor") {
                            Task { await setContactMonitoring(contact, monitored: !isContactMonitored(contact)) }
                        }
                        .buttonStyle(.bordered)
                        .tint(isContactMonitored(contact) ? .green : .blue)
                        .disabled(isLoading)
                    }
                }
                Divider()
                Text("Add New Customer")
                    .font(.caption)
                    .foregroundColor(.secondary)
                TextField("Customer name", text: $newClientName)
                    .textFieldStyle(.roundedBorder)
                TextField("Phone (optional)", text: $newClientPhone)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.phonePad)
                TextField("Email (optional)", text: $newClientEmail)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.emailAddress)
                TextField("Notes (optional)", text: $newClientNotes)
                    .textFieldStyle(.roundedBorder)
                Button("Add Customer + Monitor") {
                    Task { await addCustomerAndMonitor() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isLoading || newClientName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if !clientContacts.isEmpty {
                    Text("Customer records")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    ForEach(clientContacts.prefix(12), id: \.id) { client in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(client.name)
                                    .font(.caption2)
                                Text((client.phones + client.emails).joined(separator: " • "))
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                    .lineLimit(1)
                            }
                            Spacer()
                            Button("Remove") {
                                Task { await removeCustomer(clientID: client.id, name: client.name) }
                            }
                            .buttonStyle(.bordered)
                            .tint(.red)
                            .disabled(isLoading)
                        }
                    }
                }
                ForEach(recentTexts.prefix(4)) { item in
                    Text("• \(item.contact_name ?? item.handle ?? "Unknown"): \(item.text ?? "")")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                }
            }
            }

            if mode == .inventory {
                Section("AI Inventory Rep") {
                actionButtons(
                    primaryTitle: "Rebuild Inventory",
                    primaryIcon: "arrow.triangle.2.circlepath.circle.fill",
                    primaryAction: { Task { await rebuildInventoryNow() } },
                    secondaryTitle: "Refresh",
                    secondaryIcon: "arrow.clockwise",
                    secondaryAction: { Task { await refreshForMode() } }
                )

                if let counts = inventorySummary?.counts {
                    Text("Tracked SKUs: \(counts.inventory_rows ?? 0)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    Text("Configured stock rules: \(counts.tracked_stock_items ?? 0)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    Text("Low stock flagged: \(counts.low_stock_count ?? 0)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    Text("Manual backlog: \(counts.manual_queue_todo_count ?? 0)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }

                if let low = inventorySummary?.low_stock_items, !low.isEmpty {
                    Text("LOW STOCK")
                        .font(.caption2)
                        .foregroundColor(.orange)
                    ForEach(low.prefix(8)) { item in
                        Text("• \(item.sku) (\(item.on_hand ?? 0)/\(item.reorder_point ?? 0)) · \(item.manufacturer ?? "Unknown")")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                    }
                } else {
                    Text("No low-stock SKUs detected. Add thresholds in stock_levels.json to enable reorder alerts.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }

                if let missing = inventorySummary?.missing_stock_setup, !missing.isEmpty {
                    Text("Needs reorder rules: \(missing.prefix(5).map(\.sku).joined(separator: ", "))")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                }

                if let paths = inventorySummary?.paths {
                    if let stockFile = paths.stock_file {
                        Text("Stock config: \(stockFile)")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                            .textSelection(.enabled)
                    }
                    if let invFile = paths.inventory_csv {
                        Text("Inventory report: \(invFile)")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                            .textSelection(.enabled)
                    }
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
        .alert("Run Real Backfill?", isPresented: $showRealBackfillConfirm) {
            Button("Run \(pendingRealBackfillWeeks) Weeks", role: .destructive) {
                Task { await runIMessageBackfill(weeks: pendingRealBackfillWeeks) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This creates real tasks and drafts from past messages. Use this after reviewing dry-run counts.")
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
            turnkeyStatus = await api.fetchOpsTurnkeyStatus()
        case .dropout:
            networkDropoutStatus = await api.fetchNetworkDropoutStatus()
        case .notes:
            notesPipelineStatus = await api.fetchNotesPipelineStatus()
            contactsStatus = await api.fetchContactsStatus()
            recentTexts = (await api.fetchRecentIMessageWork(limit: 10))?.items ?? []
            iMessageAutomation = (await api.fetchIMessageAutomation())?.automation
            iMessageIntakeItems = (await api.fetchIMessageIntake(status: "draft", limit: 50))?.items ?? []
            iMessageIntakeFailures = (await api.fetchIMessageIntakeFailures(status: "pending", limit: 100))?.items ?? []
            iMessageWatchlist = (await api.fetchIMessageWatchlist())?.watchlist ?? []
            contactsList = (await api.fetchContactsList(query: contactsSearch, limit: 200))?.contacts ?? []
            clientContacts = (await api.fetchClientContacts())?.clients ?? []
        case .weather:
            break
        case .inventory:
            inventorySummary = await api.fetchOpsInventorySummary(lowStockLimit: 25, topLimit: 60)
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
            resultMessage = "Texts processed. Tasks: \(response?.tasks_created ?? 0), invoices: \(response?.invoice_drafts_created ?? 0), appointments: \(response?.appointment_drafts_created ?? 0)."
        } else {
            resultMessage = api.error ?? "Text processing failed."
        }
        await refreshForMode()
    }

    @MainActor
    private func refreshIMessageIntake() async {
        isLoading = true
        defer { isLoading = false }
        iMessageIntakeItems = (await api.fetchIMessageIntake(status: "draft", limit: 50))?.items ?? []
        iMessageIntakeFailures = (await api.fetchIMessageIntakeFailures(status: "pending", limit: 100))?.items ?? []
        resultMessage = "Intake queue refreshed (\(iMessageIntakeItems.count) pending)."
    }

    @MainActor
    private func approveInvoiceIntake(_ item: IMessageIntakeItem) async {
        guard item.kind == "invoice" else { return }
        isLoading = true
        defer { isLoading = false }
        let response = await api.approveInvoiceDraft(draftID: item.draft_id, note: "Approved from iOS intake queue", sendConfirmation: true)
        if response?.success == true {
            await refreshForMode()
            resultMessage = "Invoice approved."
        } else {
            if let failureID = response?.failure_id, !failureID.isEmpty {
                resultMessage = "Invoice action failed; queued for retry (\(failureID))."
            } else {
                resultMessage = response?.error ?? api.error ?? "Could not approve invoice draft."
            }
        }
    }

    @MainActor
    private func createCalendarFromIntake(_ item: IMessageIntakeItem) async {
        guard item.kind == "appointment" else { return }
        isLoading = true
        defer { isLoading = false }
        let response = await api.scheduleAppointmentDraft(
            draftID: item.draft_id,
            proposedStartISO: item.proposed_start,
            durationMin: 60,
            sendConfirmation: true
        )
        if response?.success == true {
            await refreshForMode()
            resultMessage = "Calendar event action complete."
        } else {
            if let failureID = response?.failure_id, !failureID.isEmpty {
                resultMessage = "Scheduling failed; queued for retry (\(failureID))."
            } else {
                resultMessage = response?.error ?? api.error ?? "Could not create calendar event."
            }
        }
    }

    @MainActor
    private func sendConfirmationForIntake(_ item: IMessageIntakeItem) async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.sendIMessageConfirmation(kind: item.kind, draftID: item.draft_id, message: nil)
        if response?.success == true {
            await refreshForMode()
            resultMessage = "Confirmation text sent."
        } else {
            if let failureID = response?.failure_id, !failureID.isEmpty {
                resultMessage = "Text send failed; queued for retry (\(failureID))."
            } else {
                resultMessage = response?.error ?? api.error ?? "Could not send confirmation text."
            }
        }
    }

    @MainActor
    private func retryIntakeFailure(_ failureID: String) async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.retryIMessageIntakeFailure(failureID: failureID)
        if response?.success == true {
            await refreshForMode()
            resultMessage = "Failure retried successfully."
        } else {
            await refreshForMode()
            resultMessage = api.error ?? "Retry failed."
        }
    }

    @MainActor
    private func retryAllIntakeFailures() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.retryAllIMessageIntakeFailures(limit: 50)
        if response?.success == true {
            await refreshForMode()
            resultMessage = "Retried \(response?.retried_count ?? 0). Resolved \(response?.resolved_count ?? 0), pending \(response?.still_pending_count ?? 0)."
        } else {
            await refreshForMode()
            resultMessage = api.error ?? "Retry all failed."
        }
    }

    private func normalizedHandle(_ value: String) -> String {
        let raw = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if raw.isEmpty { return "" }
        if raw.contains("@") {
            return raw.lowercased()
        }
        var digits = raw.replacingOccurrences(of: "[^0-9]", with: "", options: .regularExpression)
        if digits.hasPrefix("1"), digits.count == 11 {
            digits.removeFirst()
        }
        return digits.isEmpty ? raw.lowercased() : digits
    }

    private func contactHandles(_ contact: ContactListItem) -> [String] {
        let merged = contact.phones + contact.emails
        return merged.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    private func isContactMonitored(_ contact: ContactListItem) -> Bool {
        let current = Set(iMessageWatchlist.map(normalizedHandle))
        return contactHandles(contact).contains { current.contains(normalizedHandle($0)) }
    }

    @MainActor
    private func refreshContactsData() async {
        contactsList = (await api.fetchContactsList(query: contactsSearch, limit: 200))?.contacts ?? []
        iMessageWatchlist = (await api.fetchIMessageWatchlist())?.watchlist ?? iMessageWatchlist
        clientContacts = (await api.fetchClientContacts())?.clients ?? clientContacts
    }

    @MainActor
    private func syncAndRefreshContacts() async {
        isLoading = true
        defer { isLoading = false }
        _ = await api.syncContactsNow()
        await refreshContactsData()
        resultMessage = "Contacts synced and refreshed."
    }

    @MainActor
    private func seedScanListFromExistingClients() async {
        isLoading = true
        defer { isLoading = false }
        _ = await api.syncContactsNow()
        let response = await api.seedIMessageWatchlistFromContacts(
            includeClientsRegistry: true,
            includeContactsIndex: true,
            includeEmails: true,
            overwrite: false
        )
        if response?.success == true || response?.command_success == true {
            await refreshContactsData()
            let seeded = response?.seeded_count ?? 0
            let total = response?.final_watchlist_count ?? response?.watchlist_count ?? iMessageWatchlist.count
            resultMessage = "Seed complete. Added \(seeded) contact handles. Scan list total: \(total)."
        } else {
            resultMessage = response?.error ?? api.error ?? "Could not seed scan list."
        }
    }

    @MainActor
    private func setContactMonitoring(_ contact: ContactListItem, monitored: Bool) async {
        isLoading = true
        defer { isLoading = false }
        let existing = iMessageWatchlist
        let targets = contactHandles(contact)
        let targetSet = Set(targets.map(normalizedHandle))
        var merged = existing
        if monitored {
            let existingNorm = Set(existing.map(normalizedHandle))
            for handle in targets where !existingNorm.contains(normalizedHandle(handle)) {
                merged.append(handle)
            }
        } else {
            merged = existing.filter { !targetSet.contains(normalizedHandle($0)) }
        }
        let response = await api.setIMessageWatchlist(numbers: merged, monitorAll: false)
        if response?.success == true || response?.command_success == true {
            iMessageWatchlist = merged
            resultMessage = monitored ? "\(contact.name) added to scan list." : "\(contact.name) removed from scan list."
        } else {
            resultMessage = api.error ?? "Could not update scan list."
        }
    }

    @MainActor
    private func addCustomerAndMonitor() async {
        let name = newClientName.trimmingCharacters(in: .whitespacesAndNewlines)
        let phone = newClientPhone.trimmingCharacters(in: .whitespacesAndNewlines)
        let email = newClientEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty {
            resultMessage = "Customer name is required."
            return
        }
        isLoading = true
        defer { isLoading = false }
        let response = await api.addClientContact(
            name: name,
            phones: phone.isEmpty ? [] : [phone],
            emails: email.isEmpty ? [] : [email],
            notes: newClientNotes,
            autoMonitor: true
        )
        if response?.success == true {
            newClientName = ""
            newClientPhone = ""
            newClientEmail = ""
            newClientNotes = ""
            await refreshContactsData()
            resultMessage = "Customer added and watchlist updated."
        } else {
            resultMessage = response?.error ?? api.error ?? "Could not add customer."
        }
    }

    @MainActor
    private func removeCustomer(clientID: String, name: String) async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.removeClientContact(clientID: clientID, removeFromWatchlist: true)
        if response?.success == true {
            await refreshContactsData()
            resultMessage = "\(name) removed from customer records."
        } else {
            resultMessage = response?.error ?? api.error ?? "Could not remove customer."
        }
    }

    private func openContactsApp() {
        #if canImport(UIKit)
        let urls = ["contacts://", "addressbook://"]
        for item in urls {
            if let url = URL(string: item), UIApplication.shared.canOpenURL(url) {
                UIApplication.shared.open(url)
                return
            }
        }
        resultMessage = "Could not open Contacts app on this device."
        #endif
    }

    @MainActor
    private func toggleInvoiceDraftAutomation() async {
        isLoading = true
        defer { isLoading = false }
        let current = iMessageAutomation?.create_service_invoice_drafts ?? true
        let response = await api.setIMessageAutomation(createServiceInvoiceDrafts: !current, createAppointmentDrafts: nil)
        if response?.success == true || response?.command_success == true {
            iMessageAutomation = response?.automation
            resultMessage = "Invoice draft automation \((!current) ? "enabled" : "disabled")."
        } else {
            resultMessage = api.error ?? "Could not update invoice draft automation."
        }
    }

    @MainActor
    private func toggleAppointmentDraftAutomation() async {
        isLoading = true
        defer { isLoading = false }
        let current = iMessageAutomation?.create_appointment_drafts ?? true
        let response = await api.setIMessageAutomation(createServiceInvoiceDrafts: nil, createAppointmentDrafts: !current)
        if response?.success == true || response?.command_success == true {
            iMessageAutomation = response?.automation
            resultMessage = "Appointment draft automation \((!current) ? "enabled" : "disabled")."
        } else {
            resultMessage = api.error ?? "Could not update appointment draft automation."
        }
    }

    @MainActor
    private func testIMessageBackfill(weeks: Int) async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.backfillIMessages(weeks: weeks, dryRun: true, limit: 10000)
        if response?.success == true || response?.command_success == true {
            iMessageBackfillPreview = response
            resultMessage = "Backfill test complete for \(weeks) weeks."
        } else {
            resultMessage = api.error ?? "Backfill test failed."
        }
    }

    @MainActor
    private func runIMessageBackfill(weeks: Int) async {
        guard await authorizeSensitiveAction(reason: "Authorize real iMessage backfill") else {
            resultMessage = "Authentication required to run real backfill."
            return
        }
        isLoading = true
        defer { isLoading = false }
        let response = await api.backfillIMessages(weeks: weeks, dryRun: false, limit: 10000)
        if response?.success == true || response?.command_success == true {
            iMessageBackfillPreview = response
            resultMessage = "Real backfill complete for \(weeks) weeks. Tasks: \(response?.tasks_created ?? 0), invoices: \(response?.invoice_drafts_created ?? 0), appointments: \(response?.appointment_drafts_created ?? 0)."
        } else {
            resultMessage = api.error ?? "Real backfill failed."
        }
    }

    private func authorizeSensitiveAction(reason: String) async -> Bool {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            return true
        }
        return await withCheckedContinuation { continuation in
            context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) { success, _ in
                continuation.resume(returning: success)
            }
        }
    }

    @MainActor
    private func rebuildInventoryNow() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.rebuildOpsInventory(lowStockLimit: 25, topLimit: 60)
        if response?.success == true || response?.command_success == true {
            inventorySummary = response?.summary
            let lowCount = response?.summary?.counts?.low_stock_count ?? 0
            resultMessage = "Inventory rebuilt. Low stock flagged: \(lowCount)."
        } else {
            resultMessage = response?.command_error ?? api.error ?? "Inventory rebuild failed."
        }
        await refreshForMode()
    }

    @MainActor
    private func refreshTurnkeyStatus() async {
        isLoading = true
        defer { isLoading = false }
        turnkeyStatus = await api.fetchOpsTurnkeyStatus()
        if let ready = turnkeyStatus?.ready {
            resultMessage = ready ? "Turnkey status: ready." : "Turnkey status: setup still needed."
        } else {
            resultMessage = api.error ?? "Could not fetch turnkey status."
        }
    }

    @MainActor
    private func generateIntegrationBrief() async {
        isLoading = true
        defer { isLoading = false }
        let response = await api.generateOpsIntegrationBrief(noCache: false)
        if response?.success == true || response?.command_success == true {
            resultMessage = "Integration brief generated in docs/OPS_UNIFIED_BRIEF.md"
        } else {
            resultMessage = response?.command_error ?? api.error ?? "Failed to generate integration brief."
        }
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
