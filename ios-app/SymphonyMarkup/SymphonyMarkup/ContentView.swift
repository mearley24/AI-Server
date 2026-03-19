import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var settings: MarkupSettingsStore
    @EnvironmentObject var openedDocumentStore: OpenedDocumentStore
    @StateObject private var bridge = MarkupBridgeController()
    @State private var isLoading = false
    @State private var pageTitle = "Markup"
    @State private var lastError: String?
    @State private var refreshToken = 0
    @State private var selectedTab = 0
    @State private var draftURL = ""
    @State private var showImporter = false
    @State private var shareURL: URL?
    @State private var showShareSheet = false
    @State private var activeProjectStem = "markup"

    private var markupURL: URL {
        URL(string: settings.normalizedBaseURL) ?? URL(string: MarkupSettingsStore.defaultBaseURL)!
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            NavigationView {
                VStack(spacing: 0) {
                    HStack(spacing: 10) {
                        Label(isLoading ? "Loading" : "Connected", systemImage: isLoading ? "hourglass" : "dot.radiowaves.left.and.right")
                            .font(.caption)
                            .foregroundColor(isLoading ? .orange : .green)
                        Spacer()
                        Button {
                            refreshToken += 1
                        } label: {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                        .buttonStyle(.bordered)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)

                    Divider()

                    MarkupWebView(
                        bridge: bridge,
                        url: markupURL,
                        teamShareEnabled: settings.teamShareEnabled,
                        isLoading: $isLoading,
                        pageTitle: $pageTitle,
                        lastError: $lastError,
                        refreshToken: $refreshToken
                    )
                }
                .navigationTitle(pageTitle)
                .toolbar {
                    ToolbarItemGroup(placement: .navigationBarLeading) {
                        Button {
                            showImporter = true
                        } label: {
                            Image(systemName: "tray.and.arrow.down")
                        }
                        .accessibilityLabel("Import .symphony")

                        Button {
                            exportAndShareProject()
                        } label: {
                            Image(systemName: "square.and.arrow.up")
                        }
                        .accessibilityLabel("Export and Share")
                    }
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button {
                            UIPasteboard.general.string = settings.normalizedBaseURL
                        } label: {
                            Image(systemName: "doc.on.doc")
                        }
                        .accessibilityLabel("Copy URL")
                    }
                }
                .overlay(alignment: .bottom) {
                    if let err = lastError, !err.isEmpty {
                        Text("Connection issue: \(err)")
                            .font(.caption)
                            .foregroundColor(.white)
                            .padding(10)
                            .frame(maxWidth: .infinity)
                            .background(Color.red.opacity(0.9))
                    }
                }
                .fileImporter(
                    isPresented: $showImporter,
                    allowedContentTypes: [
                        UTType(filenameExtension: "symphony") ?? .json,
                        .json,
                        .plainText
                    ],
                    allowsMultipleSelection: false
                ) { result in
                    handleImport(result: result)
                }
                .onChange(of: openedDocumentStore.pendingFileURL) { _ in
                    importPendingOpenedFile()
                }
                .sheet(isPresented: $showShareSheet) {
                    if let shareURL {
                        ShareSheet(items: [shareURL])
                    }
                }
            }
            .tabItem {
                Label("Markup", systemImage: "pencil.and.outline")
            }
            .tag(0)

            NavigationView {
                Form {
                    Section("Server URL") {
                        TextField("http://bobs-mac-mini:8091", text: $draftURL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)

                        HStack {
                            Button("Use Current") {
                                draftURL = settings.baseURL
                            }
                            Spacer()
                            Button("Save URL") {
                                settings.baseURL = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
                                refreshToken += 1
                            }
                            .buttonStyle(.borderedProminent)
                        }
                    }

                    Section("Quick Targets") {
                        Button("Localhost (simulator)") {
                            draftURL = "http://localhost:8091"
                        }
                        Button("Bob host") {
                            draftURL = "http://bobs-mac-mini:8091"
                        }
                    }

                    Section("Connection Security") {
                        if isInsecureRemoteURL(settings.normalizedBaseURL) {
                            Label("Using HTTP over network. Use HTTPS for production/App Store builds.", systemImage: "exclamationmark.triangle.fill")
                                .foregroundColor(.orange)
                                .font(.footnote)
                        } else {
                            Label("Connection looks production-safe.", systemImage: "checkmark.shield.fill")
                                .foregroundColor(.green)
                                .font(.footnote)
                        }
                    }

                    Section("Storage & Sharing") {
                        Toggle("Enable Team Share", isOn: $settings.teamShareEnabled)
                        Text(settings.teamShareEnabled
                             ? "Team share is ON. Server sync and review workflows are available."
                             : "Local-only mode is ON. Files stay on-device unless you explicitly share.")
                            .font(.footnote)
                            .foregroundColor(.secondary)
                    }

                    Section("About") {
                        LabeledContent("Version", value: appVersionString())
                        LabeledContent("Bundle ID", value: Bundle.main.bundleIdentifier ?? "unknown")
                    }
                }
                .navigationTitle("Settings")
                .onAppear {
                    draftURL = settings.baseURL
                }
            }
            .tabItem {
                Label("Settings", systemImage: "gearshape")
            }
            .tag(1)
        }
    }
}

private extension ContentView {
    func importPendingOpenedFile() {
        guard let url = openedDocumentStore.consume() else { return }
        handleImport(url: url)
    }

    func handleImport(url: URL) {
        let canAccess = url.startAccessingSecurityScopedResource()
        defer {
            if canAccess { url.stopAccessingSecurityScopedResource() }
        }
        do {
            let data = try Data(contentsOf: url)
            guard let text = String(data: data, encoding: .utf8) else {
                lastError = "Import failed: unsupported file encoding."
                return
            }
            bridge.importProjectJSONString(text) { bridgeResult in
                DispatchQueue.main.async {
                    switch bridgeResult {
                    case .failure(let error):
                        lastError = "Import bridge failed: \(error.localizedDescription)"
                    case .success(let state):
                        if state != "ok" {
                            lastError = "Import bridge returned: \(state)"
                        } else {
                            let stem = url.deletingPathExtension().lastPathComponent.trimmingCharacters(in: .whitespacesAndNewlines)
                            if !stem.isEmpty {
                                activeProjectStem = sanitizeFilenameStem(stem)
                            }
                            lastError = nil
                        }
                    }
                }
            }
        } catch {
            lastError = "Import failed: \(error.localizedDescription)"
        }
    }

    func handleImport(result: Result<[URL], Error>) {
        switch result {
        case .failure(let error):
            lastError = "Import failed: \(error.localizedDescription)"
        case .success(let urls):
            guard let fileURL = urls.first else { return }
            handleImport(url: fileURL)
        }
    }

    func exportAndShareProject() {
        bridge.exportProjectJSONString { result in
            DispatchQueue.main.async {
                switch result {
                case .failure(let error):
                    lastError = "Export failed: \(error.localizedDescription)"
                case .success(let jsonText):
                    let timestamp = timestampSlug()
                    let filename = "\(sanitizeFilenameStem(activeProjectStem))_\(timestamp).symphony"
                    let outURL = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
                    do {
                        guard let data = jsonText.data(using: .utf8) else {
                            lastError = "Could not encode export payload."
                            return
                        }
                        try data.write(to: outURL, options: .atomic)
                        shareURL = outURL
                        showShareSheet = true
                        lastError = nil
                    } catch {
                        lastError = "Could not write export file: \(error.localizedDescription)"
                    }
                }
            }
        }
    }

    func sanitizeFilenameStem(_ raw: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_-"))
        let cleaned = raw.unicodeScalars.map { allowed.contains($0) ? Character($0) : "_" }
        let result = String(cleaned).replacingOccurrences(of: "__+", with: "_", options: .regularExpression)
        return result.trimmingCharacters(in: CharacterSet(charactersIn: "_")).isEmpty ? "markup" : result
    }

    func timestampSlug() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        return formatter.string(from: Date())
    }

    func appVersionString() -> String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "1"
        return "\(version) (\(build))"
    }

    func isInsecureRemoteURL(_ value: String) -> Bool {
        guard let url = URL(string: value), let scheme = url.scheme?.lowercased() else { return false }
        if scheme == "https" { return false }
        let host = url.host?.lowercased() ?? ""
        if host == "localhost" || host == "127.0.0.1" || host == "::1" { return false }
        return scheme == "http"
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
            .environmentObject(MarkupSettingsStore())
    }
}

