## 1. Planungsmodus
- Geh in den Planungsmodus bei jeder nicht-trivialen Aufgabe (3+ Schritte oder Architekturentscheidungen).
- Läuft etwas aus dem Ruder: STOPP und sofort neu planen.
- Nutze den Planungsmodus auch für Verifikationsschritte, nicht nur fürs Bauen.
- Schreib detaillierte Specs vorab, um Mehrdeutigkeit zu reduzieren.

## 2. Subagenten-Strategie
- Nutze Subagenten großzügig, um das Hauptkontextfenster sauber zu halten.
- Lagere Recherche, Exploration und parallele Analyse an Subagenten aus.
- Bei komplexen Problemen: mehr Rechenleistung über Subagenten draufwerfen.
- Eine Aufgabe pro Subagent für fokussierte Ausführung.

## 3. Selbstverbesserungs-Schleife
- Nach jeder Korrektur durch mich: das Muster in tasks/lessons.md festhalten.
- Schreib dir selbst Regeln, die denselben Fehler künftig verhindern.
- Iterier konsequent über diese Lessons, bis die Fehlerquote sinkt.
- Sichte die Lessons zum Session-Start.

## 4. Verifikation vor „fertig"
- Markiere eine Aufgabe nie als erledigt, ohne zu beweisen, dass sie funktioniert — Tests, Logs, demonstrierte Korrektheit. Verifikation (funktioniert es?) ist getrennt vom Review (ist es gut gebaut?), der global geregelt ist.
- Vergleiche das Verhalten zwischen main und deinen Änderungen, wo relevant.

## 5. Autonomes Bugfixing
- Standard bleibt autonom: Bei einem Bug-Report einfach fixen. Kein Händchenhalten verlangen. Zeig auf Logs, Fehler, fehlschlagende Tests — und behebe sie. Bring fehlschlagende CI-Tests in Ordnung, ohne dass man dir sagt, wie.
- Grenze zum Standard: Nach mehreren echten Fehlversuchen am SELBEN Problem nicht endlos Fix auf Fix auf Workaround stapeln. Wenn weiteres Probieren den Zustand verschlechtern oder ein Kartenhaus bauen würde, STOPP — leg den aktuellen Stand, die getesteten Hypothesen und das, was du als Nächstes vermutest, offen, und frag. Das gilt NICHT bei „noch nicht gelöst", sondern bei „Reparatur richtet mehr Schaden an als der Bug".

## Aufgabenverwaltung
1. **Erst planen:** Plan mit abhakbaren Punkten in tasks/todo.md schreiben.
2. **Plan abstimmen:** Vor Implementierungsbeginn kurz rückversichern.
3. **Fortschritt verfolgen:** Punkte abhaken, während du vorankommst.
4. **Änderungen erklären:** High-Level-Zusammenfassung bei jedem Schritt.
5. **Ergebnisse dokumentieren:** Review-Abschnitt in tasks/todo.md ergänzen.
6. **Lessons festhalten:** tasks/lessons.md nach Korrekturen aktualisieren.

## Optional: Projekt-Assessment
# Nur aktivieren, wenn das Projekt groß genug ist, dass eine periodische Bewertung
# Sinn ergibt. Bei kleinen Projekten weglassen. Muss meist explizit angestoßen werden.

- Nach Läufen mit struktureller Wirkung (neue Module, geänderte Schnittstellen, Architektur-Eingriffe — NICHT nach reinen Bugfixes) ein Projekt-Assessment erstellen, 1–5 Sterne pro Kategorie:
  - **Architektur** (Struktur, Kopplung, Verantwortlichkeiten)
  - **Korrektheit & Robustheit** (Edge Cases, Fehlerbehandlung, Tests)
  - **Lesbarkeit & Wartbarkeit** (Naming, Klarheit, Dokumentation)
  - **Sicherheit** (Input-Validierung, Secrets, Angriffsfläche)
- Regeln, ohne die die Zahlen wertlos sind:
  - Jede Note braucht eine konkrete Begründung am Code. Die Zahl folgt aus den Befunden, nie umgekehrt. Kein Abzug ohne Fundort, kein voller Stern ohne Grund.
  - 5/5 ist kein Standard und kein Höflichkeitswert — es bedeutet, du findest nichts zu verbessern, und das ist selten.
  - Nenne pro Kategorie die 1–2 Dinge, die den nächsten Stern bringen würden.
  - Schreibe das Assessment mit Datum in tasks/assessment.md, damit Läufe vergleichbar werden.
