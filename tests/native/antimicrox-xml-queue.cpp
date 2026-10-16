#include <QCoreApplication>
#include <QThread>
#include <QTimer>
#include <QXmlStreamReader>
#include <cstdio>
class Reader: public QObject {
 Q_OBJECT
 public slots:
 void read(QXmlStreamReader *xml) { xml->readNextStartElement(); std::puts(qPrintable(xml->name().toString())); QCoreApplication::exit(xml->name()==QStringLiteral("gamecontroller")?0:3); }
};
#include "antimicrox-xml-queue.moc"
int main(int argc, char**argv) {
 QCoreApplication app(argc,argv); QThread worker; Reader reader; reader.moveToThread(&worker); worker.start();
 QXmlStreamReader xml("<gamecontroller><sets/></gamecontroller>");
 bool queued=QMetaObject::invokeMethod(&reader,"read",Qt::QueuedConnection,Q_ARG(QXmlStreamReader*, &xml));
 if(!queued) {worker.quit(); worker.wait(); return 2;}
 QTimer::singleShot(2000,&app,[]{QCoreApplication::exit(4);});
 int result=app.exec(); worker.quit(); worker.wait(); return result;
}
