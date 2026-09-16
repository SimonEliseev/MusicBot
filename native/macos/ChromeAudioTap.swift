import Foundation
import CoreAudio
import Darwin


// MARK: - State

private var running = true


// MARK: - Logging

private func log(_ text: String) {
    fputs(text + "\n", stderr)
    fflush(stderr)
}

private func fail(
    _ text: String,
    code: Int32 = 1
) -> Never {
    log("ERROR \(text)")
    exit(code)
}

private func check(
    _ status: OSStatus,
    _ operation: String
) {
    guard status == noErr else {
        fail(
            "\(operation): OSStatus=\(status)"
        )
    }
}


// MARK: - Signals

private let signalHandler:
    @convention(c) (Int32) -> Void = { _ in
        running = false
    }

signal(SIGINT, signalHandler)
signal(SIGTERM, signalHandler)
signal(SIGPIPE, SIG_IGN)


// MARK: - Find Chrome PIDs

private func findChromePIDs() -> [pid_t] {
    let process = Process()
    let pipe = Pipe()

    process.executableURL = URL(
        fileURLWithPath: "/usr/bin/pgrep"
    )

    process.arguments = [
        "-f",
        "Google Chrome"
    ]

    process.standardOutput = pipe
    process.standardError = Pipe()

    do {
        try process.run()
        process.waitUntilExit()
    } catch {
        return []
    }

    let data =
        pipe.fileHandleForReading
            .readDataToEndOfFile()

    guard let output = String(
        data: data,
        encoding: .utf8
    ) else {
        return []
    }

    return output
        .split(separator: "\n")
        .compactMap {
            pid_t(String($0))
        }
}


// MARK: - PID -> CoreAudio process AudioObjectID

private func audioProcessObjectID(
    for pid: pid_t
) -> AudioObjectID? {

    var pidValue = pid

    var address =
        AudioObjectPropertyAddress(
            mSelector:
                kAudioHardwarePropertyTranslatePIDToProcessObject,
            mScope:
                kAudioObjectPropertyScopeGlobal,
            mElement:
                kAudioObjectPropertyElementMain
        )

    var objectID = AudioObjectID(
        kAudioObjectUnknown
    )

    var outputSize = UInt32(
        MemoryLayout<AudioObjectID>.size
    )

    let status: OSStatus =
        withUnsafePointer(
            to: &pidValue
        ) { pidPointer in

            AudioObjectGetPropertyData(
                AudioObjectID(
                    kAudioObjectSystemObject
                ),
                &address,
                UInt32(
                    MemoryLayout<pid_t>.size
                ),
                pidPointer,
                &outputSize,
                &objectID
            )
        }

    guard
        status == noErr,
        objectID != kAudioObjectUnknown
    else {
        return nil
    }

    return objectID
}


// MARK: - Tap format

private func readTapFormat(
    tapID: AudioObjectID
) -> AudioStreamBasicDescription {

    var address =
        AudioObjectPropertyAddress(
            mSelector:
                kAudioTapPropertyFormat,
            mScope:
                kAudioObjectPropertyScopeGlobal,
            mElement:
                kAudioObjectPropertyElementMain
        )

    var format =
        AudioStreamBasicDescription()

    var size = UInt32(
        MemoryLayout<
            AudioStreamBasicDescription
        >.size
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


// MARK: - PCM conversion

private func pcm16(
    _ value: Float
) -> Int16 {

    let clipped = max(
        -1.0,
        min(1.0, value)
    )

    if clipped >= 0 {
        return Int16(
            clipped * 32767.0
        )
    }

    return Int16(
        clipped * 32768.0
    )
}


// MARK: - stdout writer

private func writeAll(
    pointer: UnsafeRawPointer,
    byteCount: Int
) -> Bool {

    var written = 0

    while written < byteCount {
        let result = Darwin.write(
            STDOUT_FILENO,
            pointer.advanced(
                by: written
            ),
            byteCount - written
        )

        if result > 0 {
            written += result
            continue
        }

        if result == -1 &&
            errno == EINTR
        {
            continue
        }

        return false
    }

    return true
}


// MARK: - Find Chrome CoreAudio processes

let chromePIDs = findChromePIDs()

guard !chromePIDs.isEmpty else {
    fail(
        "Google Chrome process not found. "
        + "Start Chrome first."
    )
}

let chromeProcesses =
    chromePIDs.compactMap {
        audioProcessObjectID(
            for: $0
        )
    }

guard !chromeProcesses.isEmpty else {
    fail(
        "Chrome is running, but no "
        + "Core Audio Chrome processes "
        + "were found."
    )
}

log(
    "Chrome PIDs found: "
    + "\(chromePIDs.count)"
)

log(
    "Chrome CoreAudio processes: "
    + "\(chromeProcesses.count)"
)


// MARK: - Create Tap Description

let tapDescription =
    CATapDescription()

tapDescription.name =
    "MusicBot Chrome Tap"

// Capture ONLY these processes.
tapDescription.processes =
    chromeProcesses

// false = include listed processes.
// true = capture everything EXCEPT listed processes.
tapDescription.isExclusive =
    false

tapDescription.isPrivate =
    true

tapDescription.isMixdown =
    true

tapDescription.isMono =
    false

// Chrome keeps playing normally
// through the physical output.
tapDescription.muteBehavior =
    .unmuted

tapDescription.uuid =
    UUID()


// MARK: - Create Process Tap

var tapID = AudioObjectID(
    kAudioObjectUnknown
)

check(
    AudioHardwareCreateProcessTap(
        tapDescription,
        &tapID
    ),
    "AudioHardwareCreateProcessTap"
)

guard tapID !=
    kAudioObjectUnknown
else {
    fail(
        "CoreAudio returned "
        + "invalid tap ID"
    )
}


// MARK: - Read format

let format =
    readTapFormat(
        tapID: tapID
    )

guard
    format.mFormatID ==
        kAudioFormatLinearPCM
else {
    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "Tap output is not "
        + "Linear PCM"
    )
}

let isFloat =
    (
        format.mFormatFlags
        & kAudioFormatFlagIsFloat
    ) != 0

guard isFloat else {
    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "Tap output is not "
        + "Float PCM"
    )
}

guard
    format.mBitsPerChannel == 32
else {
    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "Expected Float32, got "
        + "\(format.mBitsPerChannel)-bit"
    )
}

guard
    format.mChannelsPerFrame >= 1
else {
    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "Tap has no audio channels"
    )
}

// Discord AudioSource expects 48 kHz.
guard
    abs(
        format.mSampleRate
        - 48_000.0
    ) < 1
else {
    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "Chrome tap sample rate is "
        + "\(format.mSampleRate) Hz. "
        + "Set macOS output device "
        + "to 48000 Hz."
    )
}

let nonInterleaved =
    (
        format.mFormatFlags
        & kAudioFormatFlagIsNonInterleaved
    ) != 0

log(
    "Tap format: "
    + "\(Int(format.mSampleRate)) Hz, "
    + "\(format.mChannelsPerFrame) ch, "
    + "Float32, "
    + (
        nonInterleaved
        ? "non-interleaved"
        : "interleaved"
    )
)


// MARK: - Create Aggregate Device

let tapConfig:
    [String: Any] = [

    kAudioSubTapUIDKey as String:
        tapDescription.uuid
            .uuidString,

    kAudioSubTapDriftCompensationKey
        as String:
        true,
]

let aggregateDescription:
    [String: Any] = [

    kAudioAggregateDeviceNameKey
        as String:
        "MusicBot Chrome Capture",

    kAudioAggregateDeviceUIDKey
        as String:
        "com.musicbot.chrome.capture."
        + UUID().uuidString,

    kAudioAggregateDeviceIsPrivateKey
        as String:
        true,

    kAudioAggregateDeviceIsStackedKey
        as String:
        false,

    // We start it manually below.
    kAudioAggregateDeviceTapAutoStartKey
        as String:
        false,

    kAudioAggregateDeviceTapListKey
        as String:
        [
            tapConfig
        ],
]

var aggregateID =
    AudioObjectID(
        kAudioObjectUnknown
    )

let aggregateStatus =
    AudioHardwareCreateAggregateDevice(
        aggregateDescription
            as CFDictionary,
        &aggregateID
    )

guard
    aggregateStatus == noErr,
    aggregateID !=
        kAudioObjectUnknown
else {
    AudioHardwareDestroyProcessTap(
        tapID
    )

    fail(
        "AudioHardwareCreateAggregateDevice: "
        + "\(aggregateStatus)"
    )
}


// MARK: - PCM Output Buffer

let maxFrames = 16_384

let outputBuffer =
    UnsafeMutablePointer<Int16>
        .allocate(
            capacity:
                maxFrames * 2
        )

defer {
    outputBuffer.deallocate()
}


// MARK: - IO callback

var ioProcID:
    AudioDeviceIOProcID?

let ioStatus =
    AudioDeviceCreateIOProcIDWithBlock(
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

        let mutableInput =
            UnsafeMutablePointer<
                AudioBufferList
            >(
                mutating:
                    inputData
            )

        let buffers =
            UnsafeMutableAudioBufferListPointer(
                mutableInput
            )

        guard !buffers.isEmpty
        else {
            return
        }

        // ---------------------------------
        // Non-interleaved Float32
        // ---------------------------------

        if nonInterleaved {

            let channelCount =
                min(
                    Int(
                        format
                            .mChannelsPerFrame
                    ),
                    buffers.count
                )

            guard channelCount > 0
            else {
                return
            }

            guard
                let firstData =
                    buffers[0]
                        .mData
            else {
                return
            }

            let firstFrames =
                Int(
                    buffers[0]
                        .mDataByteSize
                )
                /
                MemoryLayout<
                    Float
                >.size

            let frames =
                min(
                    maxFrames,
                    firstFrames
                )

            guard frames > 0
            else {
                return
            }

            for frame
                in 0..<frames
            {
                var left:
                    Float = 0

                var right:
                    Float = 0

                if channelCount == 1 {
                    let pointer =
                        firstData
                            .assumingMemoryBound(
                                to: Float.self
                            )

                    left =
                        pointer[frame]

                    right =
                        pointer[frame]

                } else {
                    if let data =
                        buffers[0]
                            .mData
                    {
                        let pointer =
                            data
                                .assumingMemoryBound(
                                    to: Float.self
                                )

                        left =
                            pointer[frame]
                    }

                    if let data =
                        buffers[1]
                            .mData
                    {
                        let pointer =
                            data
                                .assumingMemoryBound(
                                    to: Float.self
                                )

                        right =
                            pointer[frame]
                    }
                }

                outputBuffer[
                    frame * 2
                ] = pcm16(left)

                outputBuffer[
                    frame * 2 + 1
                ] = pcm16(right)
            }

            let byteCount =
                frames
                * 2
                * MemoryLayout<
                    Int16
                >.size

            if !writeAll(
                pointer:
                    UnsafeRawPointer(
                        outputBuffer
                    ),
                byteCount:
                    byteCount
            ) {
                running = false
            }

            return
        }


        // ---------------------------------
        // Interleaved Float32
        // ---------------------------------

        let buffer =
            buffers[0]

        guard
            let rawData =
                buffer.mData
        else {
            return
        }

        let pointer =
            rawData
                .assumingMemoryBound(
                    to: Float.self
                )

        let channels =
            max(
                1,
                Int(
                    buffer
                        .mNumberChannels
                )
            )

        let frames =
            min(
                maxFrames,
                Int(
                    buffer
                        .mDataByteSize
                )
                /
                (
                    MemoryLayout<
                        Float
                    >.size
                    * channels
                )
            )

        guard frames > 0
        else {
            return
        }

        for frame
            in 0..<frames
        {
            let base =
                frame * channels

            let left =
                pointer[base]

            let right:
                Float

            if channels >= 2 {
                right =
                    pointer[
                        base + 1
                    ]
            } else {
                right = left
            }

            outputBuffer[
                frame * 2
            ] = pcm16(left)

            outputBuffer[
                frame * 2 + 1
            ] = pcm16(right)
        }

        let byteCount =
            frames
            * 2
            * MemoryLayout<
                Int16
            >.size

        if !writeAll(
            pointer:
                UnsafeRawPointer(
                    outputBuffer
                ),
            byteCount:
                byteCount
        ) {
            running = false
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


// MARK: - Start capture

let startStatus =
    AudioDeviceStart(
        aggregateID,
        ioProcID
    )

guard
    startStatus == noErr
else {
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
        "AudioDeviceStart: "
        + "\(startStatus)"
    )
}

log("READY")


// MARK: - Main loop

while running {
    RunLoop.current.run(
        until:
            Date(
                timeIntervalSinceNow:
                    0.25
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

log("STOPPED")