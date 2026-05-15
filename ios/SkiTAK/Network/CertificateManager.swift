import Foundation
import Security

/// Manages the client TLS identity (PKCS12 cert + key) in the iOS Keychain.
/// The cert is imported from the enrollment data package on first join.
final class CertificateManager {

    static let shared = CertificateManager()
    private init() {}

    private let identityTag = "io.skitak.client-identity"

    // MARK: - Import

    /// Import a PKCS12 bundle received from the server enrollment package.
    func importP12(data: Data, passphrase: String) throws {
        let options: [String: Any] = [kSecImportExportPassphrase as String: passphrase]
        var items: CFArray?
        let status = SecPKCS12Import(data as CFData, options as CFDictionary, &items)
        guard status == errSecSuccess,
              let array = items as? [[String: Any]],
              let first = array.first,
              let identity = first[kSecImportItemIdentity as String] else {
            throw CertError.importFailed(status)
        }

        try saveIdentity(identity as! SecIdentity)
    }

    // MARK: - Keychain storage

    func saveIdentity(_ identity: SecIdentity) throws {
        // Remove existing before saving
        deleteIdentity()

        let query: [String: Any] = [
            kSecClass as String:            kSecClassIdentity,
            kSecValueRef as String:         identity,
            kSecAttrLabel as String:        identityTag,
            kSecAttrAccessible as String:   kSecAttrAccessibleAfterFirstUnlock,
        ]
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw CertError.saveFailed(status)
        }
    }

    func loadIdentity() -> SecIdentity? {
        let query: [String: Any] = [
            kSecClass as String:      kSecClassIdentity,
            kSecAttrLabel as String:  identityTag,
            kSecReturnRef as String:  true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else {
            return nil
        }
        return (result as! SecIdentity)
    }

    func deleteIdentity() {
        let query: [String: Any] = [
            kSecClass as String:      kSecClassIdentity,
            kSecAttrLabel as String:  identityTag,
        ]
        SecItemDelete(query as CFDictionary)
    }

    var hasIdentity: Bool { loadIdentity() != nil }

    // MARK: - Trust store

    /// Import the server CA cert so we trust the server's TLS certificate.
    func importCACert(data: Data) throws {
        guard let cert = SecCertificateCreateWithData(nil, data as CFData) else {
            throw CertError.invalidCert
        }
        let query: [String: Any] = [
            kSecClass as String:            kSecClassCertificate,
            kSecValueRef as String:         cert,
            kSecAttrLabel as String:        "io.skitak.ca-cert",
            kSecAttrAccessible as String:   kSecAttrAccessibleAfterFirstUnlock,
        ]
        SecItemDelete(query as CFDictionary)
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess || status == errSecDuplicateItem else {
            throw CertError.saveFailed(status)
        }
    }

    func loadCACert() -> SecCertificate? {
        let query: [String: Any] = [
            kSecClass as String:      kSecClassCertificate,
            kSecAttrLabel as String:  "io.skitak.ca-cert",
            kSecReturnRef as String:  true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else {
            return nil
        }
        return (result as! SecCertificate)
    }
}

enum CertError: LocalizedError {
    case importFailed(OSStatus)
    case saveFailed(OSStatus)
    case invalidCert

    var errorDescription: String? {
        switch self {
        case .importFailed(let s): return "PKCS12 import failed (OSStatus \(s))"
        case .saveFailed(let s):   return "Keychain save failed (OSStatus \(s))"
        case .invalidCert:         return "Invalid certificate data"
        }
    }
}
