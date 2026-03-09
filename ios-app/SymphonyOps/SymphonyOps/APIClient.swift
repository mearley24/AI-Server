import Foundation
import Combine
import UniformTypeIdentifiers
import Security

extension UserDefaults {
    func contains(key: String) -> Bool {
        return object(forKey: key) != nil
    }
}

/// API Client for Symphony AI Mobile API
class APIClient: ObservableObject {
    typealias URLSession = AuthenticatedURLSession

    final class AuthenticatedURLSession {
        static let shared = AuthenticatedURLSession()
        weak var apiClient: APIClient?

        private init() {}

        func data(from url: URL) async throws -> (Data, URLResponse) {
            var request = URLRequest(url: url)
            apiClient?.applyAuthHeaders(&request)
            return try await Foundation.URLSession.shared.data(for: request)
        }

        func data(for request: URLRequest) async throws -> (Data, URLResponse) {
            var mutable = request
            apiClient?.applyAuthHeaders(&mutable)
            return try await Foundation.URLSession.shared.data(for: mutable)
        }
    }

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
    @Published var apiTokenConfigured = false
    @Published var lastConnectionMessage: String?
    private let apiTokenKeychainService = "com.symphonysh.SymphonyOps.APIClient"
    private let apiTokenKeychainAccount = "symphony-api-token"

    init() {
        AuthenticatedURLSession.shared.apiClient = self
        migrateLegacyTokenFromUserDefaults()
        apiTokenConfigured = !readAPITokenFromKeychain().isEmpty
    }

    // Configure your server URL here
    // Tailscale: http://bobs-mac-mini:8420 (works anywhere)
    // Local: http://192.168.1.109:8420 (home WiFi only)
    var baseURL: String {
        UserDefaults.standard.string(forKey: "api_base_url") ?? "http://bobs-mac-mini:8420"
    }

    private var tailscaleFallbackURL: String {
        UserDefaults.standard.string(forKey: "api_tailscale_fallback_url") ?? "http://100.89.1.51:8420"
    }

    private var apiAuthToken: String {
        let keychainToken = readAPITokenFromKeychain()
        if !keychainToken.isEmpty { return keychainToken }
        let envToken = ProcessInfo.processInfo.environment["SYMPHONY_API_TOKEN"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return envToken
    }

    func setAPIToken(_ token: String) {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            clearAPIToken()
            return
        }
        writeAPITokenToKeychain(trimmed)
        UserDefaults.standard.removeObject(forKey: "api_auth_token")
        apiTokenConfigured = true
    }

    func clearAPIToken() {
        deleteAPITokenFromKeychain()
        UserDefaults.standard.removeObject(forKey: "api_auth_token")
        apiTokenConfigured = false
    }

    private func applyAuthHeaders(_ request: inout URLRequest) {
        let token = apiAuthToken
        guard !token.isEmpty else { return }
        guard shouldAttachAuth(to: request.url) else { return }
        if request.value(forHTTPHeaderField: "X-Symphony-Token") == nil {
            request.setValue(token, forHTTPHeaderField: "X-Symphony-Token")
        }
        if request.value(forHTTPHeaderField: "Authorization") == nil {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
    }

    private func shouldAttachAuth(to url: URL?) -> Bool {
        guard
            let req = url,
            let reqHost = req.host?.lowercased(),
            let api = URL(string: baseURL),
            let apiHost = api.host?.lowercased()
        else { return false }
        let reqPort = req.port ?? (req.scheme == "https" ? 443 : 80)
        let apiPort = api.port ?? (api.scheme == "https" ? 443 : 80)
        return reqHost == apiHost && reqPort == apiPort
    }

    private func migrateLegacyTokenFromUserDefaults() {
        let legacy = UserDefaults.standard.string(forKey: "api_auth_token")?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !legacy.isEmpty, readAPITokenFromKeychain().isEmpty else { return }
        writeAPITokenToKeychain(legacy)
        UserDefaults.standard.removeObject(forKey: "api_auth_token")
    }

    private func readAPITokenFromKeychain() -> String {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: apiTokenKeychainService,
            kSecAttrAccount as String: apiTokenKeychainAccount,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return "" }
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private func writeAPITokenToKeychain(_ token: String) {
        let data = Data(token.utf8)
        let attrs: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: apiTokenKeychainService,
            kSecAttrAccount as String: apiTokenKeychainAccount,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            kSecValueData as String: data
        ]
        SecItemDelete(attrs as CFDictionary)
        SecItemAdd(attrs as CFDictionary, nil)
    }

    private func deleteAPITokenFromKeychain() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: apiTokenKeychainService,
            kSecAttrAccount as String: apiTokenKeychainAccount
        ]
        SecItemDelete(query as CFDictionary)
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
        let normalized = url.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(normalized, forKey: "api_base_url")
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

    var manualDigestIntakeTemplateURL: URL? {
        URL(string: "\(baseURL)/templates/manual_digest_intake_pdf")
    }

    func downloadManualDigestIntakeTemplate() async -> URL? {
        guard let url = manualDigestIntakeTemplateURL else {
            await MainActor.run {
                self.error = "Invalid intake template URL"
            }
            return nil
        }
        do {
            var request = URLRequest(url: url)
            request.timeoutInterval = 60
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                await MainActor.run {
                    self.error = "Template download failed (HTTP \(http.statusCode))"
                }
                return nil
            }

            let tmpURL = FileManager.default.temporaryDirectory
                .appendingPathComponent("Symphony_Project_Intake_Fillable.pdf")
            try? FileManager.default.removeItem(at: tmpURL)
            try data.write(to: tmpURL, options: .atomic)
            return tmpURL
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    // MARK: - Health Check
    
    func checkConnection() async {
        let candidates = connectionCandidates(from: baseURL)
        var reachableBase: String?

        for candidate in candidates {
            guard let healthURL = URL(string: "\(candidate)/health") else { continue }
            do {
                var request = URLRequest(url: healthURL)
                request.timeoutInterval = 5
                let (_, response) = try await Foundation.URLSession.shared.data(for: request)
                if let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) {
                    reachableBase = candidate
                    break
                }
            } catch {
                continue
            }
        }

        guard let chosenBase = reachableBase else {
            await MainActor.run {
                self.isConnected = false
                self.error = "Could not connect to server. Checked: \(candidates.joined(separator: ", "))"
                self.lastConnectionMessage = self.error
            }
            return
        }

        if chosenBase != baseURL {
            UserDefaults.standard.set(chosenBase, forKey: "api_base_url")
        }

        do {
            let dashboardURL = URL(string: "\(chosenBase)/dashboard")!
            let (_, response) = try await URLSession.shared.data(from: dashboardURL)
            let code = (response as? HTTPURLResponse)?.statusCode ?? -1
            await MainActor.run {
                if code == 401 {
                    self.isConnected = false
                    self.error = "Unauthorized (token missing/invalid). Save SYMPHONY_API_TOKEN in Settings -> API Auth."
                    self.lastConnectionMessage = self.error
                    return
                }
                self.isConnected = (200...299).contains(code)
                self.error = self.isConnected ? nil : "Server reachable but returned HTTP \(code)"
                self.lastConnectionMessage = self.isConnected ? "Connected to \(chosenBase)" : self.error
            }
        } catch {
            await MainActor.run {
                self.isConnected = false
                self.error = userFacingError(error)
                self.lastConnectionMessage = self.error
            }
        }
    }

    func testURLAndToken() async -> String {
        await checkConnection()
        return await MainActor.run {
            if isConnected {
                return "Connected: \(baseURL)"
            }
            return error ?? "Disconnected"
        }
    }

    func runOneTapConnectionFix(
        preferredURL: String?,
        tokenCandidate: String?
    ) async -> String {
        let trimmedURL = (preferredURL ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedURL.isEmpty {
            setBaseURL(trimmedURL)
        }

        let trimmedToken = (tokenCandidate ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedToken.isEmpty {
            setAPIToken(trimmedToken)
        }

        await checkConnection()
        if await MainActor.run(body: { self.isConnected }) {
            return await MainActor.run { "Connected: \(self.baseURL)" }
        }

        // Force fallback host if first pass failed.
        if baseURL != tailscaleFallbackURL {
            setBaseURL(tailscaleFallbackURL)
            await checkConnection()
            if await MainActor.run(body: { self.isConnected }) {
                return await MainActor.run { "Connected after fallback: \(self.baseURL)" }
            }
        }

        return await MainActor.run {
            self.error ?? "Could not connect. Verify API is running and token is valid."
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
    func fixTradingAPI() async -> CommandResult? { await postCommandNoBody(endpoint: "/trading/fix_api") }

    // MARK: - D-Tools Product Agent

    func importDToolsProducts(
        fileURL: URL,
        createInDTools: Bool,
        maxProducts: Int,
        dealerTier: String,
        parseProfile: String,
        expectedColumns: [String],
        dryRun: Bool
    ) async -> DToolsProductImportResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/dtools/products/import")!)
            request.httpMethod = "POST"

            let boundary = "Boundary-\(UUID().uuidString)"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 300

            let startAccess = fileURL.startAccessingSecurityScopedResource()
            defer {
                if startAccess { fileURL.stopAccessingSecurityScopedResource() }
            }

            let fileData = try Data(contentsOf: fileURL)
            let filename = fileURL.lastPathComponent
            let mimeType = mimeTypeForFile(url: fileURL)

            var body = Data()
            body.append(multipartField(name: "create_in_dtools", value: createInDTools ? "true" : "false", boundary: boundary))
            body.append(multipartField(name: "max_products", value: "\(maxProducts)", boundary: boundary))
            body.append(multipartField(name: "dealer_tier", value: dealerTier, boundary: boundary))
            body.append(multipartField(name: "parse_profile", value: parseProfile, boundary: boundary))
            if !expectedColumns.isEmpty,
               let jsonData = try? JSONEncoder().encode(expectedColumns),
               let jsonString = String(data: jsonData, encoding: .utf8) {
                body.append(multipartField(name: "expected_columns_json", value: jsonString, boundary: boundary))
            }
            body.append(multipartField(name: "dry_run", value: dryRun ? "true" : "false", boundary: boundary))
            body.append(multipartFileField(name: "file", filename: filename, mimeType: mimeType, data: fileData, boundary: boundary))
            body.append("--\(boundary)--\r\n".data(using: .utf8)!)
            request.httpBody = body

            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(DToolsProductImportResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func approveAndStoreDToolsProducts(
        products: [DToolsProductDraft],
        sourceFile: String?,
        parseProfile: String?,
        dealerTier: String?,
        notes: String = ""
    ) async -> DToolsProductStoreResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/dtools/products/approve_store")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")

            let payload = DToolsProductStoreRequest(
                products: products,
                source_file: sourceFile ?? "",
                parse_profile: parseProfile ?? "auto",
                dealer_tier: dealerTier ?? "standard",
                notes: notes
            )
            request.httpBody = try JSONEncoder().encode(payload)

            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(DToolsProductStoreResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func retryCreateDToolsProducts(
        products: [DToolsProductDraft],
        sourceFile: String?,
        parseProfile: String?,
        dealerTier: String?
    ) async -> DToolsProductRetryResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/dtools/products/retry_create")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")

            let payload = DToolsProductStoreRequest(
                products: products,
                source_file: sourceFile ?? "",
                parse_profile: parseProfile ?? "auto",
                dealer_tier: dealerTier ?? "standard",
                notes: ""
            )
            request.httpBody = try JSONEncoder().encode(payload)
            request.timeoutInterval = 300

            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(DToolsProductRetryResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func runProjectManualDigest(
        projectName: String,
        fileURLs: [URL],
        runAISummary: Bool
    ) async -> ProjectManualDigestResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/projects/manual_digest")!)
            request.httpMethod = "POST"

            let boundary = "Boundary-\(UUID().uuidString)"
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 300

            var body = Data()
            body.append(multipartField(name: "project_name", value: projectName, boundary: boundary))
            body.append(multipartField(name: "run_ai_summary", value: runAISummary ? "true" : "false", boundary: boundary))

            for fileURL in fileURLs {
                let started = fileURL.startAccessingSecurityScopedResource()
                defer {
                    if started { fileURL.stopAccessingSecurityScopedResource() }
                }
                let fileData = try Data(contentsOf: fileURL)
                let filename = fileURL.lastPathComponent
                let mimeType = mimeTypeForFile(url: fileURL)
                body.append(
                    multipartFileField(
                        name: "files",
                        filename: filename,
                        mimeType: mimeType,
                        data: fileData,
                        boundary: boundary
                    )
                )
            }

            body.append("--\(boundary)--\r\n".data(using: .utf8)!)
            request.httpBody = body

            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(ProjectManualDigestResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    // MARK: - Notes Automation

    func fetchNotesPipelineStatus() async -> NotesPipelineStatusResponse? {
        do {
            let url = URL(string: "\(baseURL)/notes/pipeline_status")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(NotesPipelineStatusResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func processNoteNow(noteID: Int?, projectName: String?) async -> NotesProcessNowResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/notes/process_now")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")

            let payload = NotesProcessNowRequest(
                note_id: noteID,
                project_name: projectName,
                sync_media: true,
                run_incoming_tasks: true
            )
            request.httpBody = try JSONEncoder().encode(payload)
            request.timeoutInterval = 180

            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(NotesProcessNowResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func fetchNotesProjectLinks() async -> NotesProjectLinksResponse? {
        do {
            let url = URL(string: "\(baseURL)/notes/project_links")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(NotesProjectLinksResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func addNotesProjectLink(matchText: String, projectName: String, enabled: Bool = true) async -> NotesProjectLinksResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/notes/project_links")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let payload = NotesProjectLinkUpsertRequest(match_text: matchText, project_name: projectName, enabled: enabled)
            request.httpBody = try JSONEncoder().encode(payload)
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(NotesProjectLinksResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func fetchNotesTaskApprovals(status: String = "pending_approval", limit: Int = 25) async -> NotesTaskApprovalQueueResponse? {
        do {
            var comps = URLComponents(string: "\(baseURL)/notes/task_approvals")!
            comps.queryItems = [
                URLQueryItem(name: "status", value: status),
                URLQueryItem(name: "limit", value: String(max(1, min(limit, 200)))),
            ]
            guard let url = comps.url else { return nil }
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(NotesTaskApprovalQueueResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func approveNotesTaskApproval(approvalID: String) async -> NotesTaskApprovalActionResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/notes/task_approvals/\(approvalID)/approve")!)
            request.httpMethod = "POST"
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(NotesTaskApprovalActionResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func rejectNotesTaskApproval(approvalID: String, reason: String = "") async -> NotesTaskApprovalActionResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/notes/task_approvals/\(approvalID)/reject")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let payload = NotesTaskApprovalRejectRequest(reason: reason)
            request.httpBody = try JSONEncoder().encode(payload)
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(NotesTaskApprovalActionResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    // MARK: - Ops Health / Recovery

    func fetchOpsHealth() async -> OpsHealthResponse? {
        do {
            let url = URL(string: "\(baseURL)/ops/health")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(OpsHealthResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func runOpsRecovery(apply: Bool = true, threshold: Double = 0.8) async -> OpsRecoveryRunResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/ops/recovery/run")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let payload = OpsRecoveryRunRequest(apply: apply, threshold: threshold, playbook: nil)
            request.httpBody = try JSONEncoder().encode(payload)
            request.timeoutInterval = 120

            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(OpsRecoveryRunResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func fetchIncidentQueue(limit: Int = 20) async -> IncidentQueueResponse? {
        do {
            let url = URL(string: "\(baseURL)/tasks/incidents?limit=\(max(1, min(limit, 100)))")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(IncidentQueueResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    // MARK: - Contacts + iMessages

    func fetchContactsStatus() async -> ContactsStatusResponse? {
        do {
            let url = URL(string: "\(baseURL)/contacts/status")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(ContactsStatusResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func syncContactsNow() async -> ContactsSyncResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/contacts/sync")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data("{}".utf8)
            request.timeoutInterval = 120
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(ContactsSyncResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func fetchContactsList(query: String = "", limit: Int = 200) async -> ContactsListResponse? {
        do {
            var comps = URLComponents(string: "\(baseURL)/contacts/list")!
            comps.queryItems = [
                URLQueryItem(name: "query", value: query),
                URLQueryItem(name: "limit", value: String(max(1, min(limit, 1000)))),
            ]
            guard let url = comps.url else { return nil }
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(ContactsListResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func fetchIMessageWatchlist() async -> IMessageWatchlistResponse? {
        do {
            let url = URL(string: "\(baseURL)/imessages/watchlist")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(IMessageWatchlistResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func setIMessageWatchlist(numbers: [String], monitorAll: Bool = false) async -> IMessageWatchlistSetResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/imessages/watchlist")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let payload = IMessageWatchlistSetRequest(numbers: numbers, monitor_all: monitorAll)
            request.httpBody = try JSONEncoder().encode(payload)
            request.timeoutInterval = 60
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(IMessageWatchlistSetResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func processIMessagesNow() async -> IMessageProcessResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/imessages/process_now")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data("{}".utf8)
            request.timeoutInterval = 120
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(IMessageProcessResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func fetchRecentIMessageWork(limit: Int = 20) async -> IMessageRecentFeedResponse? {
        do {
            let capped = max(1, min(limit, 200))
            let url = URL(string: "\(baseURL)/imessages/recent?limit=\(capped)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(IMessageRecentFeedResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }

    func addClientContact(
        name: String,
        phones: [String],
        emails: [String],
        notes: String = "",
        autoMonitor: Bool = true
    ) async -> AddClientContactResponse? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/contacts/clients/add")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let payload = AddClientContactRequest(
                name: name,
                phones: phones,
                emails: emails,
                notes: notes,
                auto_monitor: autoMonitor
            )
            request.httpBody = try JSONEncoder().encode(payload)
            request.timeoutInterval = 90
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(AddClientContactResponse.self, from: data)
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return nil
        }
    }
    
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

    func askAI(question: String, source: String? = nil) async -> AskBobReply {
        // Server handles smart routing. Pass source to force: auto, cortex, ollama, lm_studio, gpt-4o-mini, perplexity
        
        do {
            let url = URL(string: "\(baseURL)/ai/chat")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 120
            
            var body: [String: String] = [
                "question": question,
                "session_id": askBobSessionId()
            ]
            let src = source ?? preferredAISource
            if src != "auto" {
                body["source"] = src
            }
            request.httpBody = try JSONEncoder().encode(body)
            
            let (data, _) = try await URLSession.shared.data(for: request)
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                return AskBobReply(
                    answer: json["output"] as? String,
                    source: json["source"] as? String ?? "unknown",
                    projectContextUsed: json["project_context_used"] as? Bool ?? false,
                    projectHint: json["project_hint"] as? String,
                    projectFilesScanned: json["project_files_scanned"] as? [String] ?? []
                )
            }
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
        }
        return AskBobReply(
            answer: nil,
            source: "error",
            projectContextUsed: false,
            projectHint: nil,
            projectFilesScanned: []
        )
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
                self.error = userFacingError(error)
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
                self.error = userFacingError(error)
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

    private func postCommandNoBody(endpoint: String) async -> CommandResult? {
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)\(endpoint)")!)
            request.httpMethod = "POST"
            let (data, _) = try await URLSession.shared.data(for: request)
            return try JSONDecoder().decode(CommandResult.self, from: data)
        } catch {
            await MainActor.run {
                self.error = userFacingError(error)
            }
            return nil
        }
    }

    private func connectionCandidates(from base: String) -> [String] {
        let trimmed = base.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), let host = url.host?.lowercased() else {
            return [trimmed]
        }
        let isLoopback = host == "127.0.0.1" || host == "localhost"
        if !isLoopback {
            return [trimmed]
        }
        let fallback = tailscaleFallbackURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if fallback.isEmpty || fallback == trimmed {
            return [trimmed]
        }
        return [trimmed, fallback]
    }

    private func userFacingError(_ error: Error) -> String {
        let nsError = error as NSError
        let text = nsError.localizedDescription.lowercased()
        if text.contains("401") || text.contains("unauthorized") {
            return "Unauthorized (token missing/invalid). Save SYMPHONY_API_TOKEN in Settings -> API Auth."
        }
        if nsError.domain == NSURLErrorDomain {
            switch nsError.code {
            case NSURLErrorCannotConnectToHost, NSURLErrorNotConnectedToInternet, NSURLErrorTimedOut:
                return "Could not connect to server. Check URL/network, then try Test URL + Token."
            default:
                break
            }
        }
        return nsError.localizedDescription
    }

    private func multipartField(name: String, value: String, boundary: String) -> Data {
        var data = Data()
        data.append("--\(boundary)\r\n".data(using: .utf8)!)
        data.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        data.append("\(value)\r\n".data(using: .utf8)!)
        return data
    }

    private func multipartFileField(
        name: String,
        filename: String,
        mimeType: String,
        data fileData: Data,
        boundary: String
    ) -> Data {
        var data = Data()
        data.append("--\(boundary)\r\n".data(using: .utf8)!)
        data.append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        data.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        data.append(fileData)
        data.append("\r\n".data(using: .utf8)!)
        return data
    }

    private func mimeTypeForFile(url: URL) -> String {
        if let contentType = UTType(filenameExtension: url.pathExtension),
           let mime = contentType.preferredMIMEType {
            return mime
        }
        return "application/octet-stream"
    }

    private func askBobSessionId() -> String {
        let key = "ask_bob_session_id"
        if let existing = UserDefaults.standard.string(forKey: key), !existing.isEmpty {
            return existing
        }
        let newValue = "symphony_ops_" + UUID().uuidString
        UserDefaults.standard.set(newValue, forKey: key)
        return newValue
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

struct AskBobReply: Codable {
    let answer: String?
    let source: String
    let projectContextUsed: Bool
    let projectHint: String?
    let projectFilesScanned: [String]
}

struct DToolsProductImportResponse: Codable {
    let success: Bool
    let file: String?
    let parsed_count: Int?
    let attempted_count: Int?
    let created_count: Int?
    let failed_count: Int?
    let create_in_dtools: Bool?
    let dealer_tier: String?
    let parse_profile: String?
    let expected_columns: [String]?
    let output_file: String?
    let error: String?
    let products: [DToolsProductDraft]?
}

struct DToolsProductDraft: Codable, Identifiable {
    var id: String { part_number ?? model }
    let brand: String?
    let model: String
    let part_number: String?
    let category: String?
    let short_description: String?
    let keywords: String?
    let unit_price: Double?
    let unit_cost: Double?
    let msrp: Double?
    let supplier: String?
}

struct DToolsProductStoreRequest: Codable {
    let products: [DToolsProductDraft]
    let source_file: String
    let parse_profile: String
    let dealer_tier: String
    let notes: String
}

struct DToolsProductStoreResponse: Codable {
    let success: Bool
    let database: String?
    let batch_id: Int?
    let saved_count: Int?
    let inserted_count: Int?
    let updated_count: Int?
    let timestamp: String?
    let error: String?
}

struct DToolsProductRetryResponse: Codable {
    let success: Bool
    let attempted_count: Int?
    let created_count: Int?
    let failed_count: Int?
    let timestamp: String?
    let error: String?
}

struct ProjectManualDigestResponse: Codable {
    let success: Bool
    let project_name: String?
    let project_slug: String?
    let batch_timestamp: String?
    let files: [ProjectManualDigestFile]?
    let digest: ProjectManualDigestData?
    let ai_summary: ProjectManualAISummary?
    let output_dir: String?
    let timestamp: String?
    let error: String?
}

struct ProjectManualDigestFile: Codable, Identifiable {
    var id: String { path ?? filename }
    let filename: String
    let path: String?
    let size_bytes: Int?
    let text_chars: Int?
    let supported: Bool?
}

struct ProjectManualDigestData: Codable {
    let recommended_notes: [String]?
    let scope_notes: [String]?
    let risk_notes: [String]?
    let open_questions: [String]?
    let detected_skus: [String]?
    let detected_brands: [String]?
    let detected_contacts: ProjectManualDigestContacts?
}

struct ProjectManualDigestContacts: Codable {
    let emails: [String]?
    let phones: [String]?
}

struct ProjectManualAISummary: Codable {
    let recommended_devices: [String]?
    let key_findings: [String]?
    let risks: [String]?
    let clarifying_questions: [String]?
    let next_steps: [String]?
}

struct NotesProcessNowRequest: Codable {
    let note_id: Int?
    let project_name: String?
    let sync_media: Bool
    let run_incoming_tasks: Bool
}

struct NotesProcessNowResponse: Codable {
    let success: Bool
    let timestamp: String?
    let note_id: Int?
    let project_name: String?
    let steps: [CommandStepResult]?
}

struct CommandStepResult: Codable {
    let step: String?
    let success: Bool?
    let output: String?
    let error: String?
}

struct NotesPipelineStatusResponse: Codable {
    let success: Bool
    let timestamp: String?
    let jobs: NotesPipelineJobs?
    let state: NotesPipelineState?
}

struct NotesPipelineJobs: Codable {
    let notes_watcher: NotesPipelineJob?
    let incoming_tasks: NotesPipelineJob?
    let notes_sync_photos: NotesPipelineJob?
}

struct NotesPipelineJob: Codable {
    let label: String?
    let loaded: Bool?
    let running: Bool?
    let pid: Int?
    let last_exit_code: Int?
}

struct NotesPipelineState: Codable {
    let notes_watcher_last_check: String?
    let notes_watcher_processed_count: Int?
    let notes_watcher_known_projects: Int?
    let incoming_tasks_last_check: String?
    let incoming_tasks_processed_count: Int?
    let incoming_tasks_completed_total: Int?
}

struct NotesProjectLinkUpsertRequest: Codable {
    let match_text: String
    let project_name: String
    let enabled: Bool
}

struct NotesProjectLinksResponse: Codable {
    let success: Bool
    let count: Int?
    let rules: [NotesProjectLinkRule]?
}

struct NotesProjectLinkRule: Codable, Identifiable {
    let rule_id: String?
    let match_text: String
    let project_name: String
    let enabled: Bool?

    var id: String { rule_id ?? "\(match_text)->\(project_name)" }

    enum CodingKeys: String, CodingKey {
        case rule_id = "id"
        case match_text
        case project_name
        case enabled
    }
}

struct NotesTaskApprovalQueueResponse: Codable {
    let success: Bool
    let count: Int
    let items: [NotesTaskApprovalItem]
}

struct NotesTaskApprovalItem: Codable, Identifiable {
    let id: String
    let status: String
    let note_id: Int?
    let note_title: String?
    let project_name: String?
    let created_at: String?
}

struct NotesTaskApprovalRejectRequest: Codable {
    let reason: String
}

struct NotesTaskApprovalActionResponse: Codable {
    let success: Bool
    let approval_id: String?
    let task_id: Int?
    let status: String?
    let error: String?
}

struct OpsRecoveryRunRequest: Codable {
    let apply: Bool
    let threshold: Double
    let playbook: String?
}

struct OpsHealthResponse: Codable {
    let success: Bool
    let status: String
    let timestamp: String?
    let problems: [String]?
    let ios_build_guardian: OpsBuildGuardianState?
    let autonomous_recovery: OpsRecoverySummary?
}

struct OpsBuildGuardianState: Codable {
    let overall_ok: Bool?
    let timestamp: String?
}

struct OpsRecoverySummary: Codable {
    let mode: String?
    let threshold: Double?
    let detected_count: Int?
    let applied_count: Int?
    let timestamp: String?
}

struct OpsRecoveryRunResponse: Codable {
    let success: Bool?
    let mode: String?
    let threshold: Double?
    let detected_count: Int?
    let applied_count: Int?
}

struct IncidentQueueResponse: Codable {
    let success: Bool
    let count: Int
    let incidents: [IncidentTask]
    let timestamp: String?
    let error: String?
}

struct IncidentTask: Codable, Identifiable {
    let id: Int
    let title: String
    let description: String
    let priority: String
    let status: String
    let assigned_to: String?
    let created_at: String?
    let updated_at: String?
}

struct ContactsStatusResponse: Codable {
    let success: Bool
    let timestamp: String?
    let contacts: ContactsSyncStatus?
}

struct ContactsSyncStatus: Codable {
    let success: Bool?
    let index_exists: Bool?
    let contacts_count: Int?
    let projects_indexed: Int?
    let timestamp: String?
}

struct ContactsSyncResponse: Codable {
    let success: Bool
    let contacts_count: Int?
    let projects_indexed: Int?
    let command_success: Bool?
    let error: String?
}

struct ContactsListResponse: Codable {
    let success: Bool
    let count: Int
    let contacts: [ContactListItem]
    let timestamp: String?
}

struct ContactListItem: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let phones: [String]
    let emails: [String]
    let linked_projects: [String]
}

struct IMessageWatchlistResponse: Codable {
    let success: Bool
    let watchlist: [String]
    let watchlist_count: Int
    let monitor_all: Bool
    let last_check: String?
}

struct IMessageWatchlistSetRequest: Codable {
    let numbers: [String]
    let monitor_all: Bool
}

struct IMessageWatchlistSetResponse: Codable {
    let success: Bool
    let watchlist_count: Int?
    let monitor_all: Bool?
    let command_success: Bool?
}

struct IMessageProcessResponse: Codable {
    let success: Bool
    let messages_seen: Int?
    let messages_monitored: Int?
    let messages_logged: Int?
    let tasks_created: Int?
    let command_success: Bool?
}

struct IMessageRecentFeedResponse: Codable {
    let success: Bool
    let count: Int
    let items: [IMessageRecentItem]
    let timestamp: String?
}

struct IMessageRecentItem: Codable, Identifiable {
    let timestamp: String?
    let rowid: Int?
    let direction: String?
    let handle: String?
    let contact_name: String?
    let linked_projects: [String]?
    let text: String?
    let task_id: Int?

    var id: String {
        "\(rowid ?? -1)-\(timestamp ?? "")-\(handle ?? "")"
    }
}

struct AddClientContactRequest: Codable {
    let name: String
    let phones: [String]
    let emails: [String]
    let notes: String
    let auto_monitor: Bool
}

struct ClientContactRecord: Codable {
    let id: String
    let name: String
    let phones: [String]
    let emails: [String]
    let notes: String?
    let created_at: String?
}

struct AddClientContactResponse: Codable {
    let success: Bool
    let client: ClientContactRecord?
    let clients_count: Int?
    let watchlist_updated: Bool?
    let error: String?
}
