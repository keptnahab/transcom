# Persönliche Full-Freigaben

Die Website liefert nach der E-Mail-Bestätigung automatisch den Beta- oder Full-Build aus. Die Entscheidung trifft ausschließlich der geschützte Ordner `transcom-private` auf STRATO.

## E-Mail freischalten oder entfernen

Öffne in Cyberduck den Ordner `amazinglighting/transcom-private/` und bearbeite dort die Datei `full-access-emails.txt`.

- Eine E-Mail-Adresse pro Zeile.
- Leerzeilen und Zeilen mit `#` am Anfang werden ignoriert.
- Groß-/Kleinschreibung spielt keine Rolle.
- Zum Entziehen einer Freigabe die betreffende Zeile löschen und speichern.

Beispiel:

```text
# Persönliche Full-Freigaben
vorname.nachname@example.com
```

Die Änderung gilt unmittelbar für neue Bestätigungslinks. Bereits erzeugte Downloadlinks bleiben höchstens sechs Stunden gültig.

## Einmalige technische Einrichtung

1. Den geprüften Full-Build mit `npm run upload:full` nach R2 hochladen.
2. In `transcom-private/config.php` den Block `full_download` mit dem R2-Dateipfad, Dateigröße und der SHA-256 des Full-Builds ausfüllen.
3. Die Vorlage `transcom-private-full-access-emails.template.txt` als `full-access-emails.txt` in den gleichen geschützten Ordner legen.

Ohne E-Mail in dieser Datei liefert die Website weiterhin nur die Beta aus.
