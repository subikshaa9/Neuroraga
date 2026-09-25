**Capsule is intended for work with devices based on physiological signals measurement and classification.**

To build one's own application the dynamic Capsule libraries (.dll / .so / .dylib) are supplied for Windows, Linux and macOS operating systems.
Apple Framework is also included for iOS operating system along with AAR for Android operating system.

## Importing the Capsule Library

Capsule provides C API and wrappers for C#, Dart, and Python. Below are examples of how to import and initialize the library in each language.

### C#

Add a reference to the `CapsuleClientSharp` library to your project, then import the namespace:

```csharp
using Capsule;

// The native library (CapsuleClient.dll on Windows, libCapsuleClient.dylib on macOS, 
// libCapsuleClient.so on Linux) should be in the same directory as your executable.
// The library is automatically loaded via P/Invoke when you use any Capsule class.

// Example: Get the library version
Console.WriteLine($"Capsule: {Capsule.Version}");

// Example: Set log level (Info is the less detailed, only the most noteworthy messages)
Capsule.Level = Capsule.LogLevel.Info;

// Example: Create a device locator
var locator = new Capsule.DeviceLocator(new Capsule.Utility.DefaultHandlerAdapter());
```

### Dart

Add the `ffi` package to your `pubspec.yaml`:

```yaml
dependencies:
  ffi: ^2.0.2
```

Import the library in your Dart code:

```dart
import 'dart:io';
import 'package:example/capsule_api.dart';  // Replace with your actual import path

// The native library (CapsuleClient.dll on Windows, libCapsuleClient.dylib on macOS/iOS,
// libCapsuleClient.so on Linux) should be accessible in your application's library path.

// Example: Get library version
String version = Capsule.version;
print("version of the library: $version");

// Example: Set log level
Capsule.logLevel = LogLevel.info;

// Example: Create a device locator
var locator = DeviceLocator();
```

### Python

Import the Capsule module and initialize it with the path to the native library:

```python
from Capsule import Capsule

# Initialize the library with the path to the native library
# Windows: './CapsuleClient.dll'
# macOS: './libCapsuleClient.dylib'
# Linux: './libCapsuleClient.so'
capsuleLib = Capsule('./libCapsuleClient.dylib')  # Adjust path for your platform

# Example: Get library version
print(f'Version: {capsuleLib.get_version()}')

# Example: Create a device locator
from DeviceLocator import DeviceLocator
device_locator = DeviceLocator('Logs', capsuleLib.get_lib())
```

**Note:** Make sure the native library file is in the correct location for your platform:
- **Windows**: `CapsuleClient.dll`
- **macOS**: `libCapsuleClient.dylib`
- **Linux**: `libCapsuleClient.so`
- **iOS**: Framework is linked during build
- **Android**: Shared library `libCapsuleClient.so` is included in the AAR CapsuleService.aar

---

## Event-Based API and Threading Requirements

**⚠️ IMPORTANT:** Capsule API is **event-based**. All responses to API calls and data updates are delivered through callbacks/events. For these callbacks to be invoked, you **must** call `DeviceLocator.Update()` periodically on the main thread.

### Threading Requirements

1. **All API calls must be made from the main thread** (or guaranteed to be sequentially consistent)
2. **`DeviceLocator.Update()` must be called periodically** on the main thread to process events and invoke callbacks
3. **Call `Update()` frequently** - typically every 40-50ms in your main loop

**Why this is necessary:** The Capsule library uses an internal event queue. The `Update()` method processes pending events and invokes registered callbacks. Without regular calls to `Update()`, callbacks will not fire, and your application will not receive device data, connection status updates, or any other events.

### C# Wrapper Exception

**⚠️ IMPORTANT FOR C# USERS:** The C# wrapper is a notable exception:

- **Delegates are called from a background thread** (not the main thread)
- **`Update()` method is NOT present** in the C# API
- **You are responsible for forwarding delegates to the main thread** - do NOT perform your logic synchronously in Capsule's callbacks

Use thread synchronization mechanisms (like `Dispatcher.Invoke` or `Task.Run`) to marshal callbacks to your main/UI thread.

### Examples

#### C/C++ Example

```cpp
#include "CCapsuleAPI.h"
#include <thread>
#include <chrono>

using namespace std::chrono_literals;

int main() {
    clCError error;
    clCDeviceLocator locator = clCDeviceLocator_Create(&error);
    
    // Set up callbacks
    clCDeviceLocator_SetOnDeviceListEvent(locator, onDeviceList);
    
    // Request devices
    clCDeviceLocator_RequestDevices(locator, clCDeviceType_Headband, 15, &error);
    
    // Main loop - MUST call Update() periodically on the main thread
    while (running) {
        clCDeviceLocator_Update(locator);  // Process events and invoke callbacks
        std::this_thread::sleep_for(40ms);  // ~25 Hz update rate
    }
    
    clCDeviceLocator_Destroy(locator);
    return 0;
}
```

#### Python Example

```python
from Capsule import Capsule
from DeviceLocator import DeviceLocator
import time

capsuleLib = Capsule('./libCapsuleClient.dylib')
device_locator = DeviceLocator('Logs', capsuleLib.get_lib())

# Set up callback
device_locator.set_on_devices_list(on_device_list)

# Request devices
device_locator.request_devices(DeviceType.Band, 10)

# Main loop - MUST call update() periodically
while running:
    device_locator.update()  # Process events and invoke callbacks
    time.sleep(0.04)  # ~25 Hz update rate (40ms)
```

#### Dart Example

```dart
import 'dart:async';

var locator = DeviceLocator();
locator.devicesHandler = onDeviceList;
locator.requestDevices(DeviceType.Headband, 15);

// Main loop - MUST call update() periodically
Timer.periodic(Duration(milliseconds: 40), (timer) {
    locator.update();  // Process events and invoke callbacks
});
```

#### C# Example (with thread marshaling)

```csharp
using System;
using System.Threading;
using System.Windows.Threading;  // For WPF
// or using System.Threading.Tasks;  // For other frameworks
using Capsule;
using Capsule.Utility;

class Program {
    private static DeviceLocator _locator;
    private static Dispatcher _dispatcher;  // WPF example
    
    static void Main(string[] args) {
        // Get the main thread dispatcher (WPF example)
        _dispatcher = Dispatcher.CurrentDispatcher;
        
        _locator = new DeviceLocator(new DefaultHandlerAdapter()) {
            // Callback will be invoked from background thread!
            OnDeviceListEvent = OnDeviceList
        };
        
        _locator.RequestDevices(DeviceType.Headband, 15);
        
        // Note: No Update() call needed in C# - events are processed automatically
        // But callbacks come from background thread, so marshal to main thread
        
        // Keep application running
        Dispatcher.Run();
    }
    
    // This callback runs on a BACKGROUND THREAD in C# wrapper
    private static void OnDeviceList(DeviceLocator locator, DeviceInfo[] devices, 
                                     DeviceLocator.FailReason failReason) {
        // ⚠️ DO NOT perform UI updates or main thread logic here directly!
        // Marshal to main thread instead:
        
        _dispatcher.Invoke(() => {
            // Now on main thread - safe to update UI or perform main thread logic
            Console.WriteLine($"Found {devices.Length} devices");
            foreach (var device in devices) {
                Console.WriteLine($"Device: {device.Description}");
            }
        });
    }
}
```

---

## Build Integration

The CapsuleAPI package contains all necessary files for integrating Capsule into your project. The package structure includes:

- **Include/** - C header files for the C API
- **Lib/** - Native library binaries (`.dll`, `.dylib`, `.so`, `.lib`)
- **Source/** - Example C++ source code
- **CMakeLists.txt** - CMake build configuration example
- **Capsule C#/** - C# wrapper source code and examples
- **Capsule Dart/** - Dart wrapper source code and examples
- **Capsule Python/** - Python wrapper source code and examples

### C/C++ (CMake)

1. **Copy the CapsuleAPI package** to your project directory.

2. **Add to your CMakeLists.txt:**

```cmake
cmake_minimum_required(VERSION 3.13)

project(YourProject)

# Find the Capsule library
find_library(CAPSULE_CLIENT_LIB CapsuleClient PATHS "${CMAKE_CURRENT_SOURCE_DIR}/CapsuleAPI/Lib")
# For Windows, you may also need the .lib file:
# find_library(CAPSULE_CLIENT_LIB CapsuleClient PATHS "${CMAKE_CURRENT_SOURCE_DIR}/CapsuleAPI/Lib")

# Add your executable
add_executable(YourApp Source/main.cpp)

# Include Capsule headers
target_include_directories(YourApp
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/CapsuleAPI/Include
)

# Link the library
target_link_libraries(YourApp ${CAPSULE_CLIENT_LIB})

# For macOS/iOS: Set rpath so the library can be found at runtime
if (APPLE)
    set_target_properties(YourApp PROPERTIES
        BUILD_WITH_INSTALL_RPATH TRUE
        INSTALL_RPATH "@executable_path/"
    )
endif()
```

3. **Include the header in your code:**

```cpp
#include "CCapsuleAPI.h"
```

4. **Ensure the native library is available at runtime:**
   - **Windows**: Copy `CapsuleClient.dll` to the same directory as your executable
   - **macOS/Linux**: Ensure `libCapsuleClient.dylib` or `libCapsuleClient.so` is in the library search path or same directory as executable

### C# (.NET)

1. **Add the C# wrapper project** to your solution:
   - Copy the `Capsule C#/CapsuleClientSharp` folder to your solution
   - Add the project reference to your application

2. **Configure the native library path** in `CapsuleClientSharp.csproj`:

```xml
<PropertyGroup>
    <LibraryPath>$(SolutionDir)../../Lib/$(OsName)/$(Arch)/$(Configuration)/$(LibraryName)</LibraryPath>
</PropertyGroup>

<ItemGroup>
    <None Include="$(LibraryPath)">
        <CopyToOutputDirectory>Always</CopyToOutputDirectory>
    </None>
</ItemGroup>
```

3. **Add project reference** in your application's `.csproj`:

```xml
<ItemGroup>
    <ProjectReference Include="..\CapsuleClientSharp\CapsuleClientSharp.csproj" />
</ItemGroup>
```

4. **The native library** (`CapsuleClient.dll`, `libCapsuleClient.dylib`, or `libCapsuleClient.so`) will be automatically copied to the output directory during build.

### Dart/Flutter

1. **Copy the Dart wrapper** to your project:
   - Copy `Capsule Dart/lib/capsule_api.dart` to your `lib/` directory

2. **Add FFI dependency** to `pubspec.yaml`:

```yaml
dependencies:
  ffi: ^2.0.2
```

3. **Place the native library** in your project:
   - **Windows**: Place `CapsuleClient.dll` in `windows/` directory
   - **macOS**: Place `libCapsuleClient.dylib` in `macos/` directory  
   - **Linux**: Place `libCapsuleClient.so` in your library path

4. **Import and use:**

```dart
import 'package:your_app/capsule_api.dart';
```

### Python

1. **Copy the Python wrapper** to your project:
   - Copy the entire `Capsule Python/CapsuleClientPython/` directory to your project

2. **Ensure the native library** is accessible:
   - Place the native library (`.dll`, `.dylib`, or `.so`) in a location accessible to your Python script
   - Or specify the full path when initializing:

```python
from Capsule import Capsule

# Specify the full path to the native library
capsuleLib = Capsule('/path/to/libCapsuleClient.dylib')
```

3. **Add to Python path** (optional):

```python
import sys
sys.path.append('/path/to/CapsuleClientPython')
```

### Android

1. **Add AAR files** to your project:
   - Copy `CapsuleService.aar` and `devicedriver.aar` from `CapsuleAPI/Android/` to your `app/libs/` directory

2. **Configure `build.gradle`:**

```gradle
android {
    repositories {
        flatDir {
            dirs 'libs'
        }
    }
}

dependencies {
    implementation(name: 'CapsuleService', ext: 'aar')
    implementation(name: 'devicedriver', ext: 'aar')
}
```

3. **Add required permissions** to `AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
<uses-permission android:name="android.permission.BLUETOOTH_SCAN" />
<uses-feature android:name="android.hardware.bluetooth_le" android:required="true" />
<!-- Additional permissions as needed -->
```

4. **Initialize in your Activity.onCreate():**

```kotlin
import com.gelo.capsule.CapsuleNative

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CapsuleNative.initCapsule(this)
    }
}
```

### iOS

1. **Add the Framework** to your Xcode project:
   - Copy `CapsuleAPI/iOS/CapsuleClient.framework` to your project directory
   - In Xcode: **File → Add Files to "YourProject"** → Select `CapsuleClient.framework`
   - Ensure "Copy items if needed" is checked

2. **Link the Framework:**
   - Select your target → **General** tab → **Frameworks, Libraries, and Embedded Content**
   - Click **+** and add `CapsuleClient.framework`
   - Set it to **Embed & Sign**

3. **Import in your code:**

```objc
#import <CapsuleClient/CCapsuleAPI.h>
```

4. **Configure Build Settings** (if needed):
   - **Framework Search Paths**: Add the path to `CapsuleClient.framework`
   - **Header Search Paths**: Add the path to `CapsuleClient.framework/Headers`

---

# How to build Examples

## Prerequisites

Before building the examples, ensure you have:

- **CMake** version 3.13 or higher
- **C++20 compatible compiler** (earlier standards will also work):
  - Windows: Visual Studio 2022 or later (with C++ desktop development workload)
  - macOS: Xcode 13.0 or later (with Command Line Tools)
  - Linux: GCC 10+ or Clang 12+
- **CapsuleAPI package** with the native library binaries in the `Lib/` directory
- **Bluetooth-enabled device** (for testing with physical devices)
- **Supported device** (Headband, Headphones, or virtual device like Noise/Sine for testing)

---

## Windows
To build with CMake use the following:
```bash
cd Example/Win
cmake -S . -B ./build -G "Visual Studio 17 2022" -A x64
cmake --build ./build --config Release
```

The executables will be located in `Example/Win/build/Release/` (or `Example/Win/build/Debug/` for Debug builds).

## MacOS
You may be prompted to grant permissions for unknown library `libCapsuleClient.dylib`.

This is a normal behavior, you can sign your app later.

For Apple Silicon CPU based devices run this command:
```zsh
arch -x86_64 zsh
```
and then proceed as usual.

To build with CMake use the following:
```bash
cd Example/Mac
cmake -S . -L ./build/libCapsuleClient.dylib -B ./build -G  "Xcode"
cmake --build ./build --config Release
```

The executables will be located in `Example/Mac/build/Release/`.

## Linux

To build with CMake use the following:

```bash
cd Example/Linux
cmake -S . -B ./build
cmake --build ./build --config Release
```

The executables will be located in `Example/Linux/build/`.

**Note:** Ensure that the native library `libCapsuleClient.so` is in your library path or in the same directory as the executable. You may need to set `LD_LIBRARY_PATH`:

```bash
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/path/to/CapsuleAPI/Lib
```

---

## Description

Above-mentioned commands will build several example executables. Here's their description and usage.

### Project Structure

The example project contains:

- **Source/main.cpp** - Main example demonstrating full Capsule API workflow
- **Source/SignalExample.cpp** - Example for raw signal data collection
- **Include/** - Header files (CCapsuleAPI.h and related headers)
- **Lib/** - Native library binaries (must be present for linking)
- **CMakeLists.txt** - Build configuration

### Main Example

This example demonstrates a complete Capsule API workflow including:

- Device discovery and connection
- Device mode switching (Signal/Resistance)
- NFB (Neurofeedback) calibration
- NFB classifier initialization and data reception
- Productivity metrics (baselines, scores, indexes)
- Cardio metrics (heart rate, stress index)
- MEMS data (accelerometer and gyroscope)
- Physiological states classification
- Emotions classification
- Battery monitoring
- Error handling

**What it demonstrates:**
- Creating a device locator and searching for devices
- Connecting to a device via Bluetooth
- Performing individual NFB calibration
- Initializing and using various classifiers
- Receiving real-time metrics and data updates
- Proper cleanup and resource management

### Usage

To run this example, `cd` to the directory where examples were built and run:

```bash
# Windows
.\build\Release\CapsuleClientExample.exe

# macOS/Linux
./build/CapsuleClientExample
```

**Expected behavior:**
1. The program will search for available devices (Headband type by default)
2. Once a device is found, it will connect automatically
3. The program will start calibration (30 seconds with eyes closed)
4. After calibration, you'll see real-time updates for:
   - NFB data (alpha, beta, theta)
   - Productivity metrics
   - Cardio data (if supported)
   - MEMS data (if supported)
   - Physiological states
   - Emotions

**Note:** The example searches for `clCDeviceType_Headband` devices. To test without a physical device, you can modify the source code to use `clCDeviceType_Noise` or `clCDeviceType_Sine` for virtual devices.

To **quit** the example press `Ctrl + C`.

### Raw Signal Example

This example demonstrates how to collect and process raw signal data directly from the device:

- **EEG data** - Raw and processed EEG signals from all channels
- **PPG data** - Photoplethysmography data (heart rate sensor)
- **MEMS data** - Accelerometer and gyroscope readings
- **PSD data** - Power Spectral Density analysis
- **EEG Artifacts** - Artifact detection information

**What it demonstrates:**
- Subscribing to raw data events
- Processing timed data streams
- Optional CSV export for data analysis
- Handling multiple data types simultaneously

### Usage

To run this example, `cd` to the directory where examples were built and run:

```bash
# Windows
.\build\Release\CapsuleSignalExample.exe --csv=true

# macOS/Linux
./build/CapsuleSignalExample --csv=true
```

This example accepts an optional argument:

- `--csv=<BOOL>` - Write signal data to a CSV file. Accepts `[true, on, 1]` for **true** and `[false, off, 0]` for **false**

You can omit the argument. In that case, the program will ask you to choose the setting during execution.

**Expected behavior:**
1. The program will search for and connect to a device
2. Raw data streams will be displayed in the console
3. If CSV export is enabled, data files will be created in the current directory
4. You'll see real-time updates for EEG, PPG, and MEMS data

**CSV Output:**
When enabled, the example creates CSV files with timestamped data for:
- EEG samples (per channel)
- PPG samples
- MEMS readings (accelerometer and gyroscope)

To **quit** the example press `Ctrl + C`.

---

## Troubleshooting

### Build Issues

**CMake can't find the library:**
- Ensure the `Lib/` directory contains the native library file (`CapsuleClient.dll`, `libCapsuleClient.dylib`, or `libCapsuleClient.so`)
- Check that the library path in `CMakeLists.txt` is correct relative to your build directory

**C++20 standard not supported:**
- Update your compiler to a version that supports C++20
- For Visual Studio, ensure you have the latest version with C++20 support enabled

**macOS: Library not found at runtime:**
- Ensure the library is in the same directory as the executable
- Or set the rpath correctly (handled automatically by CMakeLists.txt)

**Linux: Library not found:**
- Set `LD_LIBRARY_PATH` to include the library directory:
  ```bash
  export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/path/to/CapsuleAPI/Lib
  ```
- Or copy the library to a system library directory (requires root)

### Runtime Issues

**No devices found:**
- Ensure Bluetooth is enabled on your system
- Check that your device is powered on and in pairing mode
- Try using a virtual device (`clCDeviceType_Noise` or `clCDeviceType_Sine`) for testing
- Increase the search duration in the code (default is 15 seconds)

**Permission denied (macOS):**
- macOS may prompt for permissions to run the unsigned library
- Go to **System Preferences → Security & Privacy** and allow the application
- For development, you can sign the library or disable Gatekeeper temporarily

**Connection fails:**
- Ensure the device firmware is compatible (see firmware versions section in main README)
- Check that no other application is connected to the device
- Verify Bluetooth permissions are granted (especially on macOS and Linux)

**Calibration fails:**
- Ensure good electrode contact (resistance below 1000 kOhm)
- Keep eyes closed for the full calibration duration
- Minimize movement and artifacts during calibration
- Check that the device is properly positioned

---

## Next Steps

- Explore the source code in `Source/main.cpp` and `Source/SignalExample.cpp` to understand the implementation
- Check the wrapper examples in `CapsuleAPI/Capsule C#/`, `CapsuleAPI/Capsule Dart/`, and `CapsuleAPI/Capsule Python/` for language-specific examples
- Review the API reference documentation in `CapsuleAPI/Docs/`