# Lessons

## Globale Text-Replaces über Testdateien sind riskant
Beim vicare-Fix habe ich `M.` → `main.` global per Skript ersetzt, um neu eingefügte Tests zu
korrigieren — das hat aber auch **bestehende** Tests umgeschrieben, die `import src.main as M`
nutzten, und deren lokale Imports verwaisen lassen (ruff F401 fing es).
**Regel:** Bei Massen-Replaces in Dateien, die mehrere Stilkonventionen mischen, den Scope auf den
neu hinzugefügten Block begrenzen (eindeutiger Kontext-Edit) statt global. Nach jedem solchen Edit
ruff + Tests laufen lassen, bevor weitergearbeitet wird.

## TDD an „pure-vs-IO"-verschränkten Loops
Die surplus-controller-Loop verschränkt reine Entscheidung mit I/O (External-Reconcile mutiert State
per DB-Write zwischen Streak-Berechnungen). Race-/Snapshot-Fixes ließen sich trotzdem deterministisch
testen, indem eine gepatchte Abhängigkeit (z. B. `adaptive_threshold`) den State mitten im Zyklus
mutiert und man prüft, dass downstream der Snapshot vom Zyklusbeginn ankommt.
