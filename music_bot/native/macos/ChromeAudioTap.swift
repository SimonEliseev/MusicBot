import Foundation
import CoreAudio
import Darwin

private var running = true

private func log(_ text: String) {
    fputs(text + "\n", stderr)
    fflush(stderr)
}

private func fail(_ text: String, code: Int32 = 1) -> Never {
    log("ERROR \(text)")
    exit(code)
}

private func check(_ status: OSStatus, _ operation: String) {
    guard status == noErr else {
        fail("\(operation): OSStatus=\(status)")
    }
}

private let signalHandler: @convention(c) (Int32) -> Void = { _ in
    running = false
}

private func waitUntilAlive(
    _ deviceID: AudioObjectID,
    timeout: TimeInterval = 3.0
) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)

    while Date() < deadline {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceIsAlive,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        var alive: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)

        let status = AudioObjectGetPropertyData(
            deviceID,
            &address,
            0,
            nil,
            &size,
            &alive
        )

        if status == noErr && alive != 0 {
            return true
        }

        Thread.sleep(forTimeInterval: 0.1)
    }

    return false
}

private func readTapFormat(
    tapID: AudioObjectID
) -> AudioStreamBasicDescription {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioTapPropertyFormat,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )

    var format = AudioStreamBasicDescription()
    var size = UInt32(
        MemoryLayout<AudioStreamBasicDescription>.size
    )

    check(
        AudioObjectGetPropertyData(
            tapID,
            &address,
            0,
            nil,
            &size,
            &format
        ),
        "Read tap format"
    )

    return format
}

private func pcm16(_ value: Float) -> Int16 {
    let clipped = max(-1.0, min(1.0, value))

    if clipped >= 0 {
        return Int16(clipped * 32767.0)
    }

    return Int16(clipped * 32768.0)
}

private func writeAll(
    pointer: UnsafeRawPointer,
    byteCount: Int
) -> Bool {
    var written = 0

    while written < byteCount {
        let result = Darwin.write(
            STDOUT_FILENO,
            pointer.advanced(by: written),
            byteCount - written
        )

        if result > 0 {
            written += result
            continue
        }

        if result == -1 && errno == EINTR {
            continue
        }

        return false
    }

    return true
}


// MARK: - Signals

signal(SIGINT, signalHandler)
signal(SIGTERM, signalHandler)
signal(SIGPIPE, SIG_IGN)


// MARK: - Chrome process tap

let chromeBundleIDs = [
    "com.google.Chrome",
    "com.google.Chrome.helper",
    "com.google.Chrome.helper.renderer",
    "com.google.Chrome.helper.plugin",
]

let description = CATapDescription(
    stereoMixdownOfProcesses: []
)

description.name = "MusicBot Chrome Tap"
description.bundleIDs = chromeBundleIDs

// Только перечисленные Chrome-процессы.
description.isExclusive = false

description.isPrivate = true
description.isProcessRestoreEnabled = true

// Chrome продолжает обычное воспроизведение через динамики.
description.muteBehavior = .unmuted

description.uuid = UUID()

var tapID = AudioObjectID(kAudioObjectUnknown)

check(
    AudioHardwareCreateProcessTap(
        description,
        &tapID
    ),
    "AudioHardwareCreateProcessTap"
)

guard tapID != kAudioObjectUnknown else {
    fail("CoreAudio returned invalid tap ID")
}


// MARK: - Validate format

let format = readTapFormat(
    tapID: tapID
)

guard format.mFormatID == kAudioFormatLinearPCM else {
    AudioHardwareDestroyProcessTap(tapID)
    fail("Tap output is not Linear PCM")
}

let isFloat = (
    format.mFormatFlags
    & kAudioFormatFlagIsFloat
) != 0

guard isFloat else {
    AudioHardwareDestroyProcessTap(tapID)
    fail("Tap output is not Float PCM")
}

guard format.mBitsPerChannel == 32 else {
    AudioHardwareDestroyProcessTap(tapID)
    fail(
        "Expected Float32, got "
        + "\(format.mBitsPerChannel)-bit"
    )
}

guard format.mChannelsPerFrame == 2 else {
    AudioHardwareDestroyProcessTap(tapID)
    fail(
        "Expected stereo, got "
        + "\(format.mChannelsPerFrame) channels"
    )
}

// Discord PCM ожидает 48 kHz.
// Чтобы не делать лишний resampling, требуем 48 kHz от CoreAudio.
guard abs(format.mSampleRate - 48_000.0) < 1 else {
    AudioHardwareDestroyProcessTap(tapID)

    fail(
        "Chrome tap sample rate is "
        + "\(format.mSampleRate) Hz; "
        + "set macOS output device to 48000 Hz"
    )
}

let nonInterleaved = (
    format.mFormatFlags
    & kAudioFormatFlagIsNonInterleaved
) != 0

log(
    "Tap format: "
    + "\(Int(format.mSampleRate)) Hz, "
    + "stereo Float32, "
    + (nonInterleaved
        ? "non-interleaved"
        : "interleaved")
)


// MARK: - Aggregate device

let aggregateDescription: [String: Any] = [
    kAudioAggregateDeviceNameKey as String:
        "MusicBot Chrome Capture",

    kAudioAggregateDeviceUIDKey as String:
        "com.musicbot.chrome.capture.\(UUID().uuidString)",

    kAudioAggregateDeviceIsPrivateKey as String:
        true,

    kAudioAggregateDeviceIsStackedKey as String:
        false,

    kAudioAggregateDeviceTapAutoStartKey as String:
        true,

    kAudioAggregateDeviceTapListKey as String: [
        [
            kAudioSubTapUIDKey as String:
                description.uuid.uuidString,

            kAudioSubTapDriftCompensationKey as String:
                true,
        ]
    ],
]

var aggregateID = AudioObjectID(
    kAudioObjectUnknown
)

let aggregateStatus = AudioHardwareCreateAggregateDevice(
    aggregateDescription as CFDictionary,
    &aggregateID
)

guard aggregateStatus == noErr else {
    AudioHardwareDestroyProcessTap(tapID)

    fail(
        "AudioHardwareCreateAggregateDevice: "
        + "\(aggregateStatus)"
    )
}

guard waitUntilAlive(aggregateID) else {
    AudioHardwareDestroyAggregateDevice(
        aggregateID
    )

    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail("Aggregate device did not become ready")
}


// MARK: - PCM buffer

let maxFrames = 16_384

let outputBuffer = UnsafeMutablePointer<Int16>.allocate(
    capacity: maxFrames * 2
)

defer {
    outputBuffer.deallocate()
}


// MARK: - IO callback

var ioProcID: AudioDeviceIOProcID?

let ioStatus = AudioDeviceCreateIOProcIDWithBlock(
    &ioProcID,
    aggregateID,
    nil
) {
    _,
    inputData,
    _,
    _,
    _ in

    guard running else {
        return
    }

    let buffers =
        UnsafeMutableAudioBufferListPointer(
            UnsafeMutablePointer(
                mutating: inputData
            )
        )

    guard !buffers.isEmpty else {
        return
    }

    if nonInterleaved {
        guard buffers.count >= 2 else {
            return
        }

        let left = buffers[0]
        let right = buffers[1]

        guard
            let leftData = left.mData?
                .assumingMemoryBound(to: Float.self),
            let rightData = right.mData?
                .assumingMemoryBound(to: Float.self)
        else {
            return
        }

        let frames = min(
            maxFrames,
            Int(left.mDataByteSize)
                / MemoryLayout<Float>.size
        )

        guard frames > 0 else {
            return
        }

        for frame in 0..<frames {
            outputBuffer[frame * 2] =
                pcm16(leftData[frame])

            outputBuffer[frame * 2 + 1] =
                pcm16(rightData[frame])
        }

        let bytes = (
            frames
            * 2
            * MemoryLayout<Int16>.size
        )

        if !writeAll(
            pointer: UnsafeRawPointer(
                outputBuffer
            ),
            byteCount: bytes
        ) {
            running = false
        }

    } else {
        let buffer = buffers[0]

        guard
            let data = buffer.mData?
                .assumingMemoryBound(to: Float.self)
        else {
            return
        }

        let channelCount = max(
            1,
            Int(buffer.mNumberChannels)
        )

        let frames = min(
            maxFrames,
            Int(buffer.mDataByteSize)
                / (
                    MemoryLayout<Float>.size
                    * channelCount
                )
        )

        guard frames > 0 else {
            return
        }

        for frame in 0..<frames {
            let base = frame * channelCount

            outputBuffer[frame * 2] =
                pcm16(data[base])

            outputBuffer[frame * 2 + 1] =
                pcm16(
                    data[
                        base
                        + min(
                            1,
                            channelCount - 1
                        )
                    ]
                )
        }

        let bytes = (
            frames
            * 2
            * MemoryLayout<Int16>.size
        )

        if !writeAll(
            pointer: UnsafeRawPointer(
                outputBuffer
            ),
            byteCount: bytes
        ) {
            running = false
        }
    }
}

guard
    ioStatus == noErr,
    let ioProcID
else {
    AudioHardwareDestroyAggregateDevice(
        aggregateID
    )

    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "AudioDeviceCreateIOProcIDWithBlock: "
        + "\(ioStatus)"
    )
}

let startStatus = AudioDeviceStart(
    aggregateID,
    ioProcID
)

guard startStatus == noErr else {
    AudioDeviceDestroyIOProcID(
        aggregateID,
        ioProcID
    )

    AudioHardwareDestroyAggregateDevice(
        aggregateID
    )

    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "AudioDeviceStart: \(startStatus)"
    )
}

log("READY")


// MARK: - Run

while running {
    RunLoop.current.run(
        until: Date(
            timeIntervalSinceNow: 0.25
        )
    )
}


// MARK: - Cleanup

AudioDeviceStop(
    aggregateID,
    ioProcID
)

AudioDeviceDestroyIOProcID(
    aggregateID,
    ioProcID
)

AudioHardwareDestroyAggregateDevice(
    aggregateID
)

AudioHardwareDestroyProcessTap(
    tapID
)