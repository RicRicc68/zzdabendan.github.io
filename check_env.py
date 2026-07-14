"""
Diagnostica del file .env — NON stampa mai i valori delle chiavi,
solo i nomi delle variabili e i problemi di formato rilevati.
Uso: python3 check_env.py
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
print(f"Directory del progetto: {HERE}\n")

# 1. Cerca file .env e varianti sospette
candidates = sorted(HERE.glob(".env*")) + sorted(HERE.glob("*.env"))
if not candidates:
    print("❌ NESSUN file .env trovato in questa directory!")
    print("   Verifica di essere nella cartella giusta (deve stare accanto a config.py)")
    raise SystemExit(1)

for f in candidates:
    print(f"Trovato: {f.name!r}  ({f.stat().st_size} byte)")
    if f.name != ".env":
        print(f"   ⚠️  Il nome non è esattamente '.env' — "
              f"probabilmente l'editor ha aggiunto un'estensione. Rinominalo!")

env_file = HERE / ".env"
if not env_file.exists():
    print("\n❌ Il file chiamato esattamente '.env' non esiste. Fermati qui e rinominalo.")
    raise SystemExit(1)

# 2. Analizza il contenuto riga per riga (valori MAI mostrati)
raw = env_file.read_bytes()
problems = []

if raw.startswith(b"\xef\xbb\xbf"):
    problems.append("Il file inizia con un BOM UTF-8 (byte invisibili aggiunti "
                    "da alcuni editor Windows): la prima variabile non viene letta. "
                    "Risalva come UTF-8 SENZA BOM, o esegui: sed -i '1s/^\\xef\\xbb\\xbf//' .env")

text = raw.decode("utf-8-sig", errors="replace")
print("\n--- Variabili trovate nel file ---")
found_names = []
for n, line in enumerate(text.splitlines(), 1):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if "=" not in stripped:
        problems.append(f"Riga {n}: manca '=' → riga ignorata")
        continue
    name, _, value = stripped.partition("=")
    raw_name = name
    name = name.strip()
    found_names.append(name)
    masked = "(vuoto!)" if not value.strip() else f"[{len(value.strip())} caratteri]"
    print(f"  riga {n}: {name} = {masked}")
    if raw_name != raw_name.rstrip():
        problems.append(f"Riga {n}: spazi PRIMA di '=' nel nome '{name}' — toglili")
    if any(c in name for c in " \t"):
        problems.append(f"Riga {n}: il nome '{name}' contiene spazi")
    if not value.strip():
        problems.append(f"Riga {n}: '{name}' è vuota")

# 3. Verifica i nomi attesi
print("\n--- Nomi attesi dal bot ---")
expected = ["POLY_PRIVATE_KEY", "POLY_WALLET", "POLY_SIGNATURE_TYPE", "POLY_FUNDER"]
for e in expected:
    if e in found_names:
        print(f"  ✅ {e}")
    else:
        near = [f for f in found_names if e.replace("POLY_", "") in f or f in e]
        hint = f"  (forse intendevi rinominare: {near[0]}?)" if near else ""
        print(f"  ❌ {e} NON trovato{hint}")

# 4. Prova la lettura con python-dotenv (come fa config.py)
print("\n--- Test lettura con python-dotenv ---")
try:
    from dotenv import dotenv_values
    parsed = dotenv_values(env_file)
    for e in expected:
        v = parsed.get(e)
        print(f"  {e}: {'✅ letto (' + str(len(v)) + ' caratteri)' if v else '❌ non letto'}")
except ImportError:
    problems.append("python-dotenv NON installato in questo ambiente! "
                    "Esegui: pip install python-dotenv")

# 5. Verdetto
print()
if problems:
    print("⚠️  PROBLEMI RILEVATI:")
    for p in problems:
        print(f"   - {p}")
else:
    print("✅ Il file .env sembra corretto.")
    print("   Se config.py ancora non lo legge, verifica che il config.py")
    print("   aggiornato (con load_dotenv) sia davvero in QUESTA directory:")
    print("   grep -n load_dotenv config.py")
