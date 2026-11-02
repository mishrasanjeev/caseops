// Read-only macOS native trust diagnostic. No keychain mutation or networking.
import Foundation
import Security
import CryptoKit
import Darwin

func require(_ condition: Bool, _ code: String) throws {
    if !condition { throw NSError(domain: "CaseOpsNativeTrust", code: 1, userInfo: [NSLocalizedDescriptionKey: code]) }
}
func frame(_ value: stat) -> [String] {
    return [String(value.st_dev), String(value.st_ino), String(value.st_mode),
            String(value.st_uid), String(value.st_gid), String(value.st_nlink),
            String(value.st_size), String(value.st_mtimespec.tv_sec), String(value.st_mtimespec.tv_nsec),
            String(value.st_ctimespec.tv_sec), String(value.st_ctimespec.tv_nsec)]
}
func parentFrames(_ url: URL) throws -> [[String]] {
    var parent = url.deletingLastPathComponent()
    var rows = [[String]]()
    while true {
        let name = parent.path
        try require(rows.count < 128 && parent.resolvingSymlinksInPath().path == name,
                    "CANONICAL_PARENT_REQUIRED")
        var value = stat()
        try require(lstat(name, &value) == 0 && (value.st_mode & S_IFMT) == S_IFDIR,
                    "NONLINK_DIRECTORY_PARENT_REQUIRED")
        rows.append([name, String(value.st_dev), String(value.st_ino), String(value.st_mode),
                     String(value.st_uid), String(value.st_gid)])
        if name == "/" { return rows }
        parent.deleteLastPathComponent()
    }
}
func readCertificate(_ name: String, _ digest: String) throws -> Data {
    let url = URL(fileURLWithPath: name)
    try require(name.hasPrefix("/") && url.standardizedFileURL.path == name && url.resolvingSymlinksInPath().path == name,
                "CANONICAL_PUBLIC_CERTIFICATE_REQUIRED")
    let parents = try parentFrames(url)
    let fd = open(name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
    try require(fd >= 0, "CERTIFICATE_DESCRIPTOR_REQUIRED")
    defer { close(fd) }
    var before = stat(), named = stat()
    try require(fstat(fd, &before) == 0 && lstat(name, &named) == 0, "CERTIFICATE_METADATA_REQUIRED")
    try require((before.st_mode & S_IFMT) == S_IFREG && before.st_nlink == 1 && before.st_uid == getuid()
                && before.st_size > 0 && before.st_size <= 16384 && frame(before) == frame(named), "OWNED_PUBLIC_CERTIFICATE_REQUIRED")
    var bytes = [UInt8](repeating: 0, count: Int(before.st_size) + 1)
    var offset = 0
    while offset < bytes.count {
        let width = bytes.count - offset
        let count = bytes.withUnsafeMutableBytes { raw in
            Darwin.read(fd, raw.baseAddress!.advanced(by: offset), width)
        }
        try require(count >= 0, "CERTIFICATE_READ_FAILED")
        if count == 0 { break }
        offset += count
    }
    var after = stat(), final = stat()
    try require(fstat(fd, &after) == 0 && lstat(name, &final) == 0 && offset == Int(before.st_size)
                && frame(before) == frame(after) && frame(before) == frame(final), "CERTIFICATE_CHANGED")
    let data = Data(bytes.prefix(offset))
    let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    try require(actual == digest, "CERTIFICATE_DIGEST_CHANGED")
    try require(try parentFrames(url) == parents, "PUBLIC_CERTIFICATE_NAMESPACE_CHANGED")
    try require(url.resolvingSymlinksInPath().path == name, "PUBLIC_CERTIFICATE_NAMESPACE_CHANGED")
    return data
}

do {
    try require(CommandLine.arguments.count == 3, "ONE_PUBLIC_CERTIFICATE_AND_SHA256_REQUIRED")
    let digest = CommandLine.arguments[2]
    let approvedPublicRoots = [
        "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b": "denied.der",
        "96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6": "positive.der"
    ]
    try require(approvedPublicRoots[digest] == URL(fileURLWithPath: CommandLine.arguments[1]).lastPathComponent,
                "FIXED_PUBLIC_ROOT_DIAGNOSTIC_INPUT_REQUIRED")
    let data = try readCertificate(CommandLine.arguments[1], digest)
    guard let certificate = SecCertificateCreateWithData(nil, data as CFData) else {
        throw NSError(domain: "CaseOpsNativeTrust", code: 2)
    }
    var trust: SecTrust?
    try require(SecTrustCreateWithCertificates(certificate, SecPolicyCreateBasicX509(), &trust) == errSecSuccess,
                "DEFAULT_NATIVE_TRUST_REQUIRED")
    guard let current = trust else { throw NSError(domain: "CaseOpsNativeTrust", code: 3) }
    try require(SecTrustSetNetworkFetchAllowed(current, false) == errSecSuccess, "NETWORK_FETCH_MUST_BE_DISABLED")
    var error: CFError?
    let accepted = SecTrustEvaluateWithError(current, &error)
    let result: [String: Any] = ["schemaVersion": 1, "certificateSha256": digest,
                               "nativeBasicX509Accepted": accepted, "networkFetchAllowed": false,
                               "explicitAnchorsConfigured": false, "globalTrustMutation": false,
                               "errorDomain": error.map { CFErrorGetDomain($0) as String } ?? "",
                               "errorCode": error.map { CFErrorGetCode($0) } ?? 0,
                               "scope": "macOS Security default basic-X509 anchor evaluation; not curl HTTPS or iOS acceptance"]
    let output = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(output)
    FileHandle.standardOutput.write(Data([10]))
} catch {
    FileHandle.standardError.write(Data("CaseOps native public trust diagnostic failed.\n".utf8))
    exit(1)
}
