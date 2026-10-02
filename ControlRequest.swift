import Foundation

/// Internal one-request transport. Python exposes named controls; this second
/// boundary excludes firmware, reset, delete, loop discard and raw commands.
struct ControlRequest: Decodable {
    let device_uuid: String
    let created_at: Double
    let action: String
    let command: UInt16
    let feature: UInt16
    let value_hex: String?
    let setting_write: Bool
    let response_feature: UInt16

    func packet(identifier: String, now: Double) throws -> Data {
        enum Invalid: Error { case request }
        func require(_ ok: Bool) throws { if !ok { throw Invalid.request } }
        try require(device_uuid.uppercased() == identifier.uppercased())
        try require(created_at.isFinite && (0...120).contains(now - created_at))
        let readFeatures: Set<UInt16> = [0x000D, 0x3440, 0x3000, 0x3001, 0x3002,
            0x3040, 0x3041, 0x3042, 0x3100, 0x3101, 0x3102, 0x3103, 0x3104,
            0x3107, 0x3140, 0x3141, 0x3143, 0x3145, 0x3146, 0x3147,
            0x3148, 0x314A, 0x314B, 0x3805]
        func le(_ n: UInt16) -> [UInt8] { [UInt8(n & 255), UInt8(n >> 8)] }
        var value = [UInt8]()
        let chars = Array(value_hex ?? "")
        try require(chars.count % 2 == 0 && chars.count <= 2048)
        for i in stride(from: 0, to: chars.count, by: 2) {
            guard let byte = UInt8(String(chars[i...i+1]), radix: 16) else { throw Invalid.request }
            value.append(byte)
        }
        if command == 1 {
            try require(!setting_write && value.isEmpty && readFeatures.contains(feature)
                        && response_feature == feature)
            return Data([0, 0xDD, 1, 0, 1, 0, 2, 0] + le(feature))
        }
        try require(command == 2)
        if !setting_write {
            switch feature {
            case 0x3441: try require(value.count == 1 && (1...4).contains(value[0]) && response_feature == 0x3442)
            case 0x3443: try require(value.count == 1 && (1...254).contains(value[0]) && response_feature == 0x3444)
            case 0x3405: try require(value.count == 2 && value[0] <= 4 && value[1] <= 4 && response_feature == 0x3406)
            case 0x3400: try require(value.count == 1 && value[0] <= 4 && response_feature == 0x3401)
            case 0x3803: try require(value.count == 1 && response_feature == 0x3804)
            default: throw Invalid.request
            }
        } else {
            try require(response_feature == feature)
            switch feature {
            case 0x3442:
                try require(value.count == 2 && (1...4).contains(value[0]) && (1...254).contains(value[1]))
            case 0x3446:
                try require(value.count >= 6 && (1...4).contains(value[0]) && [1,3,4,9].contains(value[1])
                            && (1...254).contains(value[2]) && value[3] == 255
                            && value.count == 6 + Int(value[5]))
                try require(String(bytes: value.dropFirst(6), encoding: .utf8) != nil)
                if [3,4].contains(value[1]) { try require(value[2] >= 51) }
            case 0x3445:
                try require(value.count >= 8 && (1...4).contains(value[0]) && (1...254).contains(value[1])
                            && (1...4).contains(value[2]) && value[3] <= 7
                            && value.count == 8 + Int(value[7]) * 5)
                if value[2] == 4 { try require(value[7] == 1 && value[4] <= 30 && value[5] <= 11) }
                if value[2] == 1 { try require(value[6] <= 1) }
                if value[2] == 2 || value[2] == 3 {
                    try require(value[7] == 0 && value[4] <= 30 && value[5] <= 11 && value[6] == 255)
                }
                for i in stride(from: 8, to: value.count, by: 5) {
                    let bits = (0..<4).reduce(UInt32(0)) { $0 | UInt32(value[i+1+$1]) << ($1*8) }
                    let n = Float(bitPattern: bits)
                    try require(n.isFinite && (0...1000).contains(n))
                }
            case 0x3000, 0x3040, 0x3100, 0x3107:
                try require(value.count == 1 && value[0] <= 1)
            case 0x3001, 0x3041:
                try require(value.count == 1 && (30...240).contains(value[0]))
            case 0x3002, 0x3042, 0x3101, 0x3102, 0x3104:
                try require(value.count == 1)
            case 0x3103:
                try require(value.count == 2 && (4200...4600).contains(Int(value[0]) + 256 * Int(value[1])))
            case 0x3145:
                try require(value.count == 1 && value[0] <= 3)
            case 0x3140:
                try require(value.count == 1 && value[0] <= 1)
            case 0x3147:
                try require(value.count == 1 && [1,2,4,8,12,16,24,32].contains(value[0]))
            case 0x3406:
                try require(value.count == 3 && value[0] <= 4 && value[1] <= 4 && value[2] <= 32)
            default: throw Invalid.request
            }
        }
        let body = le(feature) + le(UInt16(value.count)) + value
        return Data([0, 0xDD, 2, 0, 1, 0] + le(UInt16(body.count)) + body)
    }
}
