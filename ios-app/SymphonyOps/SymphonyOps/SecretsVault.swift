import SwiftUI
import CryptoKit
import LocalAuthentication
import Security
import UIKit

struct VaultSecretRecord: Codable, Identifiable, Hashable {
    let id: UUID
    var keyName: String
    var provider: String
    var tags: [String]
    var encryptedValueB64: String
    var valueHashPrefix: String
    var last4: String
    var createdAt: Date
    var updatedAt: Date
    var lastRotatedAt: Date?
    var expiresAt: Date?
    var notes: String
}

struct VaultImportCandidate: Identifiable, Hashable {
    let id = UUID()
    var keyName: String
    var provider: String
    var tags: [String]
    var value: String
}

struct VaultImportPreviewRow: Identifiable, Hashable {
    let id = UUID()
    var sourceLine: String
    var keyName: String?
    var status: String // import | skip
    var reason: String
}

@MainActor
final class SecretsVaultStore: ObservableObject {
    @Published var records: [VaultSecretRecord] = []
    @Published var errorMessage: String?

    private let storageURL: URL
    private let keychainService = "com.symphonysh.SymphonyOps.SecretsVault"
    private let keychainAccount = "vault-master-key-v1"

    init() {
        let fm = FileManager.default
        let dir = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("SymphonyOps", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        storageURL = dir.appendingPathComponent("secrets_vault_records.json")
        load()
    }

    func load() {
        guard let data = try? Data(contentsOf: storageURL) else {
            records = []
            return
        }
        do {
            records = try JSONDecoder().decode([VaultSecretRecord].self, from: data)
                .sorted { $0.updatedAt > $1.updatedAt }
        } catch {
            errorMessage = "Vault load failed: \(error.localizedDescription)"
        }
    }

    func save() {
        do {
            let data = try JSONEncoder().encode(records)
            try data.write(to: storageURL, options: .atomic)
        } catch {
            errorMessage = "Vault save failed: \(error.localizedDescription)"
        }
    }

    func addSecret(
        keyName: String,
        provider: String,
        tagsCSV: String,
        value: String,
        notes: String = "",
        expiresAt: Date? = nil
    ) {
        let trimmedValue = value.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedName = keyName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty, !trimmedValue.isEmpty else { return }
        do {
            let key = try fetchOrCreateMasterKey()
            let encrypted = try encryptString(trimmedValue, key: key)
            let now = Date()
            let tags = tagsCSV
                .split(separator: ",")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
                .filter { !$0.isEmpty }
            let newRecord = VaultSecretRecord(
                id: UUID(),
                keyName: trimmedName,
                provider: provider.trimmingCharacters(in: .whitespacesAndNewlines),
                tags: Array(Set(tags)).sorted(),
                encryptedValueB64: encrypted,
                valueHashPrefix: Self.hashPrefix(trimmedValue),
                last4: Self.last4(trimmedValue),
                createdAt: now,
                updatedAt: now,
                lastRotatedAt: now,
                expiresAt: expiresAt,
                notes: notes.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            records.append(newRecord)
            records.sort { $0.updatedAt > $1.updatedAt }
            save()
        } catch {
            errorMessage = "Add secret failed: \(error.localizedDescription)"
        }
    }

    func updateMetadata(for id: UUID, provider: String, tagsCSV: String, notes: String, expiresAt: Date?) {
        guard let idx = records.firstIndex(where: { $0.id == id }) else { return }
        var r = records[idx]
        r.provider = provider.trimmingCharacters(in: .whitespacesAndNewlines)
        r.tags = tagsCSV.split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
            .filter { !$0.isEmpty }
        r.notes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        r.expiresAt = expiresAt
        r.updatedAt = Date()
        records[idx] = r
        save()
    }

    func rotateSecret(id: UUID, newValue: String) {
        let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let idx = records.firstIndex(where: { $0.id == id }) else { return }
        do {
            let key = try fetchOrCreateMasterKey()
            var r = records[idx]
            r.encryptedValueB64 = try encryptString(trimmed, key: key)
            r.valueHashPrefix = Self.hashPrefix(trimmed)
            r.last4 = Self.last4(trimmed)
            r.updatedAt = Date()
            r.lastRotatedAt = Date()
            records[idx] = r
            save()
        } catch {
            errorMessage = "Rotate secret failed: \(error.localizedDescription)"
        }
    }

    func deleteSecret(id: UUID) {
        records.removeAll { $0.id == id }
        save()
    }

    func revealSecret(id: UUID) async -> String? {
        guard let record = records.first(where: { $0.id == id }) else { return nil }
        do {
            let ok = try await biometricGate()
            guard ok else { return nil }
            let key = try fetchOrCreateMasterKey()
            return try decryptString(record.encryptedValueB64, key: key)
        } catch {
            errorMessage = "Reveal failed: \(error.localizedDescription)"
            return nil
        }
    }

    func authenticateUser() async -> Bool {
        (try? await biometricGate()) ?? false
    }

    func copySecretSecure(id: UUID, clearAfter seconds: TimeInterval = 30) async -> Bool {
        guard let value = await revealSecret(id: id) else { return false }
        copyWithAutoClear(value, clearAfter: seconds)
        return true
    }

    func copyWithAutoClear(_ value: String, clearAfter seconds: TimeInterval = 30) {
        UIPasteboard.general.string = value
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            if UIPasteboard.general.string == value {
                UIPasteboard.general.string = ""
            }
        }
    }

    func parseImportCandidates(rawText: String) -> [VaultImportCandidate] {
        var out: [VaultImportCandidate] = []
        let lines = rawText.split(whereSeparator: \.isNewline)
        for raw in lines {
            let line = String(raw).trimmingCharacters(in: .whitespacesAndNewlines)
            if line.isEmpty || line.hasPrefix("#") { continue }
            if let idx = line.firstIndex(of: "=") {
                let key = String(line[..<idx]).trimmingCharacters(in: .whitespacesAndNewlines)
                let value = String(line[line.index(after: idx)...]).trimmingCharacters(in: .whitespacesAndNewlines)
                if !key.isEmpty && !value.isEmpty {
                    out.append(VaultImportCandidate(keyName: key, provider: providerGuess(key), tags: tagGuess(key), value: value))
                }
                continue
            }
            if let idx = line.firstIndex(of: ":") {
                let key = String(line[..<idx]).trimmingCharacters(in: .whitespacesAndNewlines)
                let value = String(line[line.index(after: idx)...]).trimmingCharacters(in: .whitespacesAndNewlines)
                if !key.isEmpty && !value.isEmpty && looksLikeSecretValue(value) {
                    out.append(VaultImportCandidate(keyName: key, provider: providerGuess(key), tags: tagGuess(key), value: value))
                }
            }
        }
        // dedupe by key, keep first
        var seen: Set<String> = []
        return out.filter { item in
            let k = item.keyName.lowercased()
            if seen.contains(k) { return false }
            seen.insert(k)
            return true
        }
    }

    func importCandidates(_ candidates: [VaultImportCandidate]) {
        for c in candidates where !c.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            addSecret(
                keyName: c.keyName,
                provider: c.provider,
                tagsCSV: c.tags.joined(separator: ","),
                value: c.value,
                notes: "Imported into encrypted vault",
                expiresAt: nil
            )
        }
    }

    func previewImportCandidates(rawText: String) -> [VaultImportPreviewRow] {
        var rows: [VaultImportPreviewRow] = []
        var seen: Set<String> = []
        let lines = rawText.split(whereSeparator: \.isNewline)
        for raw in lines {
            let line = String(raw).trimmingCharacters(in: .whitespacesAndNewlines)
            if line.isEmpty || line.hasPrefix("#") {
                rows.append(VaultImportPreviewRow(sourceLine: line, keyName: nil, status: "skip", reason: "Comment/blank"))
                continue
            }

            var parsedKey = ""
            var parsedValue = ""

            if let idx = line.firstIndex(of: "=") {
                parsedKey = String(line[..<idx]).trimmingCharacters(in: .whitespacesAndNewlines)
                parsedValue = String(line[line.index(after: idx)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            } else if let idx = line.firstIndex(of: ":") {
                parsedKey = String(line[..<idx]).trimmingCharacters(in: .whitespacesAndNewlines)
                parsedValue = String(line[line.index(after: idx)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            } else {
                rows.append(VaultImportPreviewRow(sourceLine: line, keyName: nil, status: "skip", reason: "No separator"))
                continue
            }

            if parsedKey.isEmpty || parsedValue.isEmpty {
                rows.append(VaultImportPreviewRow(sourceLine: line, keyName: nil, status: "skip", reason: "Missing key/value"))
                continue
            }
            if !looksLikeSecretValue(parsedValue) {
                rows.append(VaultImportPreviewRow(sourceLine: line, keyName: parsedKey, status: "skip", reason: "Value does not look like secret"))
                continue
            }
            let keyLower = parsedKey.lowercased()
            if seen.contains(keyLower) {
                rows.append(VaultImportPreviewRow(sourceLine: line, keyName: parsedKey, status: "skip", reason: "Duplicate key"))
                continue
            }
            seen.insert(keyLower)
            rows.append(VaultImportPreviewRow(sourceLine: line, keyName: parsedKey, status: "import", reason: "Ready"))
        }
        return rows
    }

    private func providerGuess(_ key: String) -> String {
        let k = key.lowercased()
        if k.contains("openai") { return "OpenAI" }
        if k.contains("anthropic") { return "Anthropic" }
        if k.contains("perplexity") { return "Perplexity" }
        if k.contains("telegram") { return "Telegram" }
        if k.contains("twilio") { return "Twilio" }
        if k.contains("github") { return "GitHub" }
        if k.contains("supabase") { return "Supabase" }
        if k.contains("dtools") { return "D-Tools" }
        if k.contains("zoho") { return "Zoho" }
        if k.contains("mqtt") { return "MQTT" }
        return "General"
    }

    private func tagGuess(_ key: String) -> [String] {
        [providerGuess(key).lowercased(), "credential"]
    }

    private func looksLikeSecretValue(_ value: String) -> Bool {
        let v = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if v.count < 8 { return false }
        if v.contains(" ") { return false }
        if v.hasPrefix("http://") || v.hasPrefix("https://") { return false }
        if v.lowercased().hasPrefix("sk_") { return true }
        if v.lowercased().hasPrefix("sk-") { return true }
        if v.lowercased().hasPrefix("ghp_") { return true }
        if v.lowercased().hasPrefix("xoxb-") { return true }
        if v.lowercased().hasPrefix("xoxp-") { return true }
        if v.lowercased().hasPrefix("pat_") { return true }
        // Generic high-entropy token-ish fallback.
        let charset = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_-./+=:"))
        return v.rangeOfCharacter(from: charset.inverted) == nil
    }

    private static func hashPrefix(_ value: String) -> String {
        let digest = SHA256.hash(data: Data(value.utf8))
        return digest.compactMap { String(format: "%02x", $0) }.joined().prefix(12).description
    }

    private static func last4(_ value: String) -> String {
        let clean = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard clean.count > 4 else { return clean }
        return String(clean.suffix(4))
    }

    private func biometricGate() async throws -> Bool {
        let context = LAContext()
        context.localizedCancelTitle = "Cancel"
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else { return false }
        return try await withCheckedThrowingContinuation { cont in
            context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Unlock Secrets Vault") { success, err in
                if let err {
                    cont.resume(throwing: err)
                } else {
                    cont.resume(returning: success)
                }
            }
        }
    }

    private func fetchOrCreateMasterKey() throws -> SymmetricKey {
        if let data = readKeychainData() {
            return SymmetricKey(data: data)
        }
        let keyData = Data((0..<32).map { _ in UInt8.random(in: .min ... .max) })
        try writeKeychainData(keyData)
        return SymmetricKey(data: keyData)
    }

    private func encryptString(_ value: String, key: SymmetricKey) throws -> String {
        let sealed = try AES.GCM.seal(Data(value.utf8), using: key)
        guard let combined = sealed.combined else {
            throw NSError(domain: "Vault", code: -1, userInfo: [NSLocalizedDescriptionKey: "Encryption failed"])
        }
        return combined.base64EncodedString()
    }

    private func decryptString(_ b64: String, key: SymmetricKey) throws -> String {
        guard let data = Data(base64Encoded: b64) else {
            throw NSError(domain: "Vault", code: -2, userInfo: [NSLocalizedDescriptionKey: "Invalid encrypted data"])
        }
        let sealed = try AES.GCM.SealedBox(combined: data)
        let decrypted = try AES.GCM.open(sealed, using: key)
        guard let value = String(data: decrypted, encoding: .utf8) else {
            throw NSError(domain: "Vault", code: -3, userInfo: [NSLocalizedDescriptionKey: "Decode failed"])
        }
        return value
    }

    private func readKeychainData() -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess else { return nil }
        return item as? Data
    }

    private func writeKeychainData(_ data: Data) throws {
        let attributes: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            kSecValueData as String: data
        ]
        SecItemDelete(attributes as CFDictionary)
        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw NSError(domain: "Vault", code: Int(status), userInfo: [NSLocalizedDescriptionKey: "Keychain write failed (\(status))"])
        }
    }
}

struct SecretsVaultView: View {
    @EnvironmentObject var vault: SecretsVaultStore
    private enum VaultSheetMode { case reveal, rotate }
    private enum RotationFilter: String, CaseIterable, Identifiable {
        case all = "All"
        case rotateNow = "Rotate Now"
        case aging = "Aging+"
        var id: String { rawValue }
    }
    @State private var filter = ""
    @State private var rotationFilter: RotationFilter = .all
    @State private var neverShowValues = true
    @State private var showAdd = false
    @State private var showImport = false
    @State private var addName = ""
    @State private var addProvider = "General"
    @State private var addTags = ""
    @State private var addValue = ""
    @State private var addNotes = ""
    @State private var activeRecord: VaultSecretRecord?
    @State private var vaultSheetMode: VaultSheetMode = .reveal
    @State private var revealedValue: String = ""
    @State private var lastCopyStatus = ""
    @State private var importRawText = ""
    @State private var importCandidates: [VaultImportCandidate] = []
    @State private var importPreviewRows: [VaultImportPreviewRow] = []
    @State private var pendingDeleteRecord: VaultSecretRecord?
    @State private var rotationStatusMessage = ""

    var filtered: [VaultSecretRecord] {
        let q = filter.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let base = vault.records.filter {
            matchesRotationFilter($0)
        }
        guard !q.isEmpty else { return base }
        return base.filter {
            $0.keyName.lowercased().contains(q) ||
                $0.provider.lowercased().contains(q) ||
                $0.tags.joined(separator: " ").lowercased().contains(q)
        }
    }

    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Vault Controls")) {
                    Picker("Rotation Filter", selection: $rotationFilter) {
                        ForEach(RotationFilter.allCases) { rf in
                            Text(rf.rawValue).tag(rf)
                        }
                    }
                    .pickerStyle(.segmented)
                    HStack {
                        Button("Add Secret") { showAdd = true }
                            .buttonStyle(.borderedProminent)
                        Button("Import From Note Text") { showImport = true }
                            .buttonStyle(.bordered)
                    }
                    TextField("Search by key/provider/tag", text: $filter)
                        .textFieldStyle(.roundedBorder)
                    Toggle("Never show value (copy-only secure mode)", isOn: $neverShowValues)
                    Text("Values are masked by default. Reveal requires device authentication.")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    if !lastCopyStatus.isEmpty {
                        Text(lastCopyStatus)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                    if !rotationStatusMessage.isEmpty {
                        Text(rotationStatusMessage)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                }

                Section(header: Text("Stored Secrets (\(filtered.count))")) {
                    ForEach(filtered) { item in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(item.keyName).font(.subheadline).fontWeight(.semibold)
                                Spacer()
                                Text(item.provider).font(.caption2).foregroundColor(.secondary)
                            }
                            Text("••••\(item.last4)  |  hash \(item.valueHashPrefix)")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            rotationBadgeView(for: item)
                            if !item.tags.isEmpty {
                                Text(item.tags.joined(separator: ", "))
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                            HStack {
                                if neverShowValues {
                                    Button("Copy Secure") {
                                        Task {
                                            let ok = await vault.copySecretSecure(id: item.id, clearAfter: 30)
                                            lastCopyStatus = ok
                                                ? "Copied \(item.keyName) (clipboard auto-clears in 30s)."
                                                : "Copy cancelled or failed."
                                        }
                                    }
                                    .buttonStyle(.bordered)
                                } else {
                                    Button("Reveal") {
                                        Task {
                                            if let value = await vault.revealSecret(id: item.id) {
                                                vaultSheetMode = .reveal
                                                activeRecord = item
                                                revealedValue = value
                                            }
                                        }
                                    }
                                    .buttonStyle(.bordered)
                                }
                                Button("Rotate") {
                                    vaultSheetMode = .rotate
                                    activeRecord = item
                                    revealedValue = ""
                                }
                                    .buttonStyle(.bordered)
                                Button("Delete", role: .destructive) { pendingDeleteRecord = item }
                                    .buttonStyle(.bordered)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .navigationTitle("Secrets Vault")
            .alert("Vault Error", isPresented: Binding(get: {
                vault.errorMessage != nil
            }, set: { _ in
                vault.errorMessage = nil
            })) {
                Button("OK", role: .cancel) { vault.errorMessage = nil }
            } message: {
                Text(vault.errorMessage ?? "")
            }
            .alert("Delete Secret?", isPresented: Binding(get: {
                pendingDeleteRecord != nil
            }, set: { show in
                if !show { pendingDeleteRecord = nil }
            })) {
                Button("Delete", role: .destructive) {
                    if let rec = pendingDeleteRecord {
                        vault.deleteSecret(id: rec.id)
                    }
                    pendingDeleteRecord = nil
                }
                Button("Cancel", role: .cancel) {
                    pendingDeleteRecord = nil
                }
            } message: {
                Text("This removes the encrypted record permanently.")
            }
            .sheet(isPresented: $showAdd) {
                NavigationView {
                    Form {
                        TextField("Env key (e.g. OPENAI_API_KEY)", text: $addName)
                        TextField("Provider", text: $addProvider)
                        TextField("Tags (comma-separated)", text: $addTags)
                        SecureField("Secret value", text: $addValue)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled(true)
                        TextField("Notes", text: $addNotes)
                    }
                    .navigationTitle("Add Secret")
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Cancel") {
                                addName = ""; addProvider = "General"; addTags = ""; addValue = ""; addNotes = ""
                                showAdd = false
                            }
                        }
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Save") {
                                vault.addSecret(
                                    keyName: addName,
                                    provider: addProvider,
                                    tagsCSV: addTags,
                                    value: addValue,
                                    notes: addNotes
                                )
                                addName = ""; addProvider = "General"; addTags = ""; addValue = ""; addNotes = ""
                                showAdd = false
                            }.disabled(addName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || addValue.isEmpty)
                        }
                    }
                }
            }
            .sheet(isPresented: $showImport) {
                NavigationView {
                    Form {
                        Section(header: Text("Paste Raw Note Text")) {
                            TextEditor(text: $importRawText)
                                .frame(minHeight: 160)
                            Button("Parse Candidates") {
                                importPreviewRows = vault.previewImportCandidates(rawText: importRawText)
                                importCandidates = vault.parseImportCandidates(rawText: importRawText)
                                importRawText = ""
                            }
                            .buttonStyle(.bordered)
                        }
                        if !importPreviewRows.isEmpty {
                            Section(header: Text("Preview (\(importPreviewRows.count) lines)")) {
                                ForEach(importPreviewRows.prefix(40)) { row in
                                    VStack(alignment: .leading, spacing: 3) {
                                        HStack {
                                            Image(systemName: row.status == "import" ? "checkmark.circle.fill" : "xmark.circle")
                                                .foregroundColor(row.status == "import" ? .green : .secondary)
                                            Text(row.keyName ?? row.sourceLine)
                                                .font(.caption)
                                                .lineLimit(1)
                                        }
                                        Text(row.reason)
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                    }
                                }
                            }
                        }
                        Section(header: Text("Candidates (\(importCandidates.count))")) {
                            ForEach(importCandidates) { c in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(c.keyName).font(.subheadline).fontWeight(.semibold)
                                    Text("\(c.provider) • \(c.tags.joined(separator: ", "))")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                    Text("value hidden")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                        }
                    }
                    .navigationTitle("Import to Vault")
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Cancel") {
                                importRawText = ""
                                importCandidates = []
                                importPreviewRows = []
                                showImport = false
                            }
                        }
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Import") {
                                vault.importCandidates(importCandidates)
                                importRawText = ""
                                importCandidates = []
                                importPreviewRows = []
                                showImport = false
                            }.disabled(importCandidates.isEmpty)
                        }
                    }
                }
            }
            .sheet(item: $activeRecord) { record in
                NavigationView {
                    Form {
                        if vaultSheetMode == .reveal && !revealedValue.isEmpty {
                            Section(header: Text("Revealed Value")) {
                                Text(revealedValue)
                                    .font(.system(.body, design: .monospaced))
                                    .textSelection(.enabled)
                                Button("Copy (auto-clear 30s)") {
                                    vault.copyWithAutoClear(revealedValue, clearAfter: 30)
                                }
                            }
                        } else {
                            Section(header: Text("Rotate Secret")) {
                                Text("Enter replacement value. Current value is never shown in this mode.")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                                SecureField("New secret value", text: $addValue)
                                    .textInputAutocapitalization(.never)
                                    .autocorrectionDisabled(true)
                                Button("Save Rotation") {
                                    Task {
                                        let authed = await vault.authenticateUser()
                                        guard authed else {
                                            rotationStatusMessage = "Rotation cancelled (auth required)."
                                            return
                                        }
                                        vault.rotateSecret(id: record.id, newValue: addValue)
                                        rotationStatusMessage = "Rotation saved for \(record.keyName)."
                                        addValue = ""
                                        activeRecord = nil
                                    }
                                }
                                .disabled(addValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            }
                        }
                    }
                    .navigationTitle("Vault Item")
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Close") {
                                revealedValue = ""
                                addValue = ""
                                activeRecord = nil
                            }
                        }
                    }
                }
            }
        }
    }

    private func rotationBadgeView(for item: VaultSecretRecord) -> some View {
        let days = daysSinceRotation(item)
        let (label, color): (String, Color) = {
            if days >= 90 { return ("Rotate Now (90d+)", .red) }
            if days >= 30 { return ("Aging (30d+)", .orange) }
            if days >= 7 { return ("Review (7d+)", .blue) }
            return ("Fresh (<7d)", .green)
        }()
        return HStack(spacing: 6) {
            Text(label)
                .font(.caption2)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(color.opacity(0.14))
                .foregroundColor(color)
                .clipShape(Capsule())
            Text("\(days)d since rotate")
                .font(.caption2)
                .foregroundColor(.secondary)
        }
    }

    private func daysSinceRotation(_ item: VaultSecretRecord) -> Int {
        let last = item.lastRotatedAt ?? item.updatedAt
        return max(0, Calendar.current.dateComponents([.day], from: last, to: Date()).day ?? 0)
    }

    private func matchesRotationFilter(_ item: VaultSecretRecord) -> Bool {
        let days = daysSinceRotation(item)
        switch rotationFilter {
        case .all:
            return true
        case .rotateNow:
            return days >= 90
        case .aging:
            return days >= 30
        }
    }
}
