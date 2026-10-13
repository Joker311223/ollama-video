import Foundation
import Security

// Secrets travel through stdin/stdout pipes, never command-line arguments.
let input = FileHandle.standardInput.readDataToEndOfFile()
func reply(_ object: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: object)
    FileHandle.standardOutput.write(data)
}
do {
    let args = try JSONSerialization.jsonObject(with: input) as? [String: String] ?? [:]
    let operation = args["operation"] ?? "status"
    let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "local.jingxu.storyboardstudio.ark",
        kSecAttrAccount as String: "api-key"]
    var status: OSStatus = errSecSuccess
    if operation == "set" {
        guard let secret = args["value"], !secret.isEmpty else { throw NSError(domain: "Keychain", code: -50) }
        let changes = [kSecValueData as String: Data(secret.utf8)]
        status = SecItemUpdate(query as CFDictionary, changes as CFDictionary)
        if status == errSecItemNotFound {
            var item = query; item[kSecValueData as String] = Data(secret.utf8)
            status = SecItemAdd(item as CFDictionary, nil)
        }
        reply(["ok": status == errSecSuccess, "status": Int(status)])
    } else if operation == "delete" {
        status = SecItemDelete(query as CFDictionary)
        reply(["ok": status == errSecSuccess || status == errSecItemNotFound, "status": Int(status)])
    } else {
        var lookup = query
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        lookup[operation == "get" ? kSecReturnData as String : kSecReturnAttributes as String] = true
        var result: CFTypeRef?
        status = SecItemCopyMatching(lookup as CFDictionary, &result)
        var output: [String: Any] = ["ok": status == errSecSuccess || status == errSecItemNotFound,
                                   "configured": status == errSecSuccess, "status": Int(status)]
        if operation == "get", status == errSecSuccess, let data = result as? Data {
            output["value"] = String(data: data, encoding: .utf8) ?? ""
        }
        reply(output)
    }
} catch { reply(["ok": false, "status": -50]) }
