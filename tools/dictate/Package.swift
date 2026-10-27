// swift-tools-version: 6.2
import PackageDescription

// MARVIN Dictate (marvin#730): hold Fn, talk, and the words are typed where the cursor is. On-device, no usage cap.
let package = Package(
    name: "MarvinDictate",
    platforms: [.macOS(.v26)],
    products: [.executable(name: "MarvinDictate", targets: ["MarvinDictate"])],
    targets: [
        .target(name: "DictateCore"),
        .executableTarget(name: "MarvinDictate", dependencies: ["DictateCore"]),
        .testTarget(name: "DictateCoreTests", dependencies: ["DictateCore"]),
    ],
    swiftLanguageModes: [.v5]
)
