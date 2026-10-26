# AntiMicroX 3.6.1 profile reader compatibility

Upstream `src/xml/inputdevicexml.cpp` queues `readConfigSig(QXmlStreamReader*)`
across threads without registering that pointer type in `src/main.cpp`.
With the official 3.6.1 Qt6 AppImage, this produces `Cannot queue arguments`
followed by `Could not open mutex_read_config`: the application remains running
but does not read the profile.

This small library registers that single type before main. The managed launcher
loads it only when bundled Qt6 is present. It clears LD_PRELOAD before AntiMicroX
can launch any children. It does not replace Qt or modify profiles or system
libraries. Python decodes the checked payload atomically to the managed runtime.

The x86_64 payload was compiled with GCC 13 and Qt 6.4.2 headers, linked against
libQt6Core.so.6 from the official 3.6.1 AppImage. Its minimum Qt symbol version
is Qt_6.4 and its minimum glibc symbol versions are GLIBC_2.2.5 and GLIBC_2.4.
`build.sh` rebuilds it with Ubuntu 24.04 development packages. Update the Python
checksum after rebuilding; binary output may vary with toolchain versions.

Validation used the official bundled Qt libraries and a queued invocation of a
slot reading a gamecontroller XML document. Without the library, Qt rejects the
unregistered argument; with it, the receiver thread reads the document. Hardware
mapping and the editing/focus workflow were subsequently confirmed on the
Batocera v44/labwc test machine. This validates that tested setup, not every
controller, game or runner. See [the native integration guide](../../../docs/ANTIMICROX.md).
