// AntiMicroX 3.6.1 omits this registration before its queued profile reader.
// Loaded only by the managed Qt6 AntiMicroX process; never system-wide.
#include <QMetaType>
#include <QXmlStreamReader>
#include <cstdlib>

Q_DECLARE_METATYPE(QXmlStreamReader *)
namespace {
const int xmlReaderType = [] {
    const int type = qRegisterMetaType<QXmlStreamReader *>("QXmlStreamReader*");
    // Profile actions may launch child processes. Do not preload into them.
    unsetenv("LD_PRELOAD");
    return type;
}();
}
