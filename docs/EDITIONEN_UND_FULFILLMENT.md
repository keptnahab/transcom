# TransCom Starter und Full

## Produktgrenzen

| Funktion | Starter | Full |
| --- | --- | --- |
| Gespeicherte Transkripte ansehen, bearbeiten und verwalten | ja | ja |
| Neue Live-/Datei-Transkription | maximal exakt 60 Sekunden | unbegrenzt |
| TXT-/CSV-Export | serverseitig gesperrt | erlaubt |
| Preis | Beta-/Einstiegsedition | einmalig 295 EUR |

Starter ist der sichere Default. Fehlt ein Editionsmerkmal oder ist es
unlesbar, startet Backend und Oberfläche als Starter.

## Technische Entscheidung fuer den ersten Verkauf

Der erste kleine Verkauf verwendet zwei getrennte, eindeutig benannte
Apple-Silicon-Builds. Jedes App-Bundle enthaelt ein `edition.json`; Electron
liest dieses Merkmal aus den App-Ressourcen und uebergibt es an das lokale
Backend. Ein Aufrufparameter kann die Edition eines gepackten Builds nicht
ueberschreiben.

Das ist offline, einfach zu supporten und erfindet weder Lizenzserver noch
Checkout-Anbindung. Es ist keine manipulationssichere Lizenz: Ein technisch
versierter Kunde kann ein lokal kontrolliertes, nicht notarisiertes App-Bundle
patchen. Fuer den initialen, persoenlich betreuten Verkauf ist diese Grenze
bewusst akzeptiert. Vor einem breiten Self-Service-Vertrieb sollte sie durch
eine signierte Offline-Lizenz ersetzt werden:

1. separates Ed25519-Signierschluesselpaar; privater Schluessel nur beim
   Fulfillment, oeffentlicher Schluessel in der App,
2. Lizenzinhalt mit Lizenz-ID, Edition, Kunde und optionalem Ablaufdatum,
3. kanonische Serialisierung und Signaturpruefung vor Backendstart,
4. Starter-Fallback bei fehlender oder ungueltiger Signatur,
5. Widerruf/Mehrgeraeteregel erst definieren, bevor ein Checkout automatisiert
   wird.

## Manueller Fulfillment-Ablauf

1. Zahlung von einmalig 295 EUR ausserhalb der App bestaetigen.
2. Ausschliesslich das Full-Artefakt mit seinem veroeffentlichten SHA-256 an
   den Kunden geben; Starter und Full nicht unter demselben Dateinamen ablegen.
3. Kunde verifiziert SHA-256 vor dem Oeffnen.
4. Kaufbeleg, Buildversion, Artefakt-Hash und Empfaenger intern protokollieren.
5. Keine Zusage von Developer-ID-Signatur oder Apple-Notarisierung machen,
   solange beides nicht tatsaechlich vorliegt.

## Build

`npm run build:editions` erzeugt beide Editionen aus demselben Renderer-,
Backend- und Modellstand. Die Ausgaben liegen getrennt unter `dist/starter/`
und `dist/full/`. Der Build schreibt vor jedem Electron-Paketlauf das passende
Editionsmanifest und verwendet unterschiedliche App-IDs und Produktnamen.

## Noch noetig fuer Checkout und automatisches Fulfillment

- rechtliche Preis-/Umsatzsteuerdarstellung und Rechnungsprozess,
- Zahlungsanbieter und Webhook-Verifikation,
- Zuordnung Zahlung zu Lizenz/Download,
- sicherer Download mit Ablauf oder Kundenportal,
- Developer-ID-Signatur und Apple-Notarisierung,
- Support-, Update- und Rueckerstattungsprozess,
- signierte Offline-Lizenz, bevor Full als Self-Service-Download angeboten
  wird.
