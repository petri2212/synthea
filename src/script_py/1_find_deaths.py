"""
Script 1 - Trova pazienti deceduti + causa della morte
=======================================================
Scansiona tutti i file JSON di una cartella e individua i pazienti
deceduti cercando questi segnali FHIR:

  1. Campo 'deceasedDateTime' nel resource Patient
  2. Campo 'deceasedBoolean: true' nel resource Patient
  3. Encounter di tipo 'Death Certification' (SNOMED 308646001)
  4. Observation con codice 'Cause of Death' (LOINC 69453-9)
     -> estrae anche il testo della causa (valueCodeableConcept)
  5. DiagnosticReport / DocumentReference con LOINC 69409-1

Output: stampa a schermo + salva 'deceduti.txt' nella cartella dello script

Utilizzo:
    python 1_trova_deceduti.py /percorso/cartella/fhir
"""

import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DEATH_CERT_LOINC     = {"69409-1"}
CAUSE_OF_DEATH_LOINC = {"69453-9"}
DEATH_CERT_SNOMED    = {"308646001"}
DEATH_KEYWORDS       = {"death certificate", "death certification",
                         "cause of death", "certificate of death"}


def estrai_nome(patient_resource):
    for n in patient_resource.get("name", []):
        if n.get("use") == "official":
            parts = n.get("prefix", []) + n.get("given", []) + [n.get("family", "")]
            return " ".join(parts).strip()
    if patient_resource.get("name"):
        n = patient_resource["name"][0]
        return (" ".join(n.get("given", [])) + " " + n.get("family", "")).strip()
    return "Sconosciuto"


def _match_coding(codings):
    for c in codings:
        code    = c.get("code", "")
        display = c.get("display", "").lower()
        if code in DEATH_CERT_LOINC:
            return f"LOINC {code}: {c.get('display', '')}"
        if code in CAUSE_OF_DEATH_LOINC:
            return f"LOINC {code}: {c.get('display', '')}"
        if code in DEATH_CERT_SNOMED:
            return f"SNOMED {code}: {c.get('display', '')}"
        if any(kw in display for kw in DEATH_KEYWORDS):
            return f"display: {c.get('display', '')}"
    return None


def cerca_decesso(entries):
    """
    Restituisce (lista_segnali, causa_morte_str).
    """
    motivi     = []
    causa_morte = None

    for entry in entries:
        resource = entry.get("resource", {})
        rtype    = resource.get("resourceType", "")

        if rtype == "Patient":
            dt = resource.get("deceasedDateTime")
            if dt:
                motivi.append(f"deceasedDateTime: {dt}")
            elif resource.get("deceasedBoolean") is True:
                motivi.append("deceasedBoolean: true")

        elif rtype == "Encounter":
            for tipo in resource.get("type", []):
                m = _match_coding(tipo.get("coding", []))
                if m:
                    motivi.append(f"Encounter -> {m}")
                    break

        elif rtype == "Observation":
            m = _match_coding(resource.get("code", {}).get("coding", []))
            if m:
                motivi.append(f"Observation -> {m}")
                # Estrai causa morte da valueCodeableConcept
                vcc = resource.get("valueCodeableConcept", {})
                testo = vcc.get("text", "")
                if not testo:
                    for c in vcc.get("coding", []):
                        if c.get("display"):
                            testo = c["display"]
                            break
                if testo:
                    causa_morte = testo

        elif rtype == "DiagnosticReport":
            m = _match_coding(resource.get("code", {}).get("coding", []))
            if m:
                motivi.append(f"DiagnosticReport -> {m}")

        elif rtype == "DocumentReference":
            m = _match_coding(resource.get("type", {}).get("coding", []))
            if m:
                motivi.append(f"DocumentReference -> {m}")

    # Deduplicazione
    seen, dedup = set(), []
    for x in motivi:
        if x not in seen:
            seen.add(x)
            dedup.append(x)

    return dedup, causa_morte


def analizza_cartella(cartella_str):
    cartella   = Path(cartella_str).resolve()
    script_dir = Path(__file__).parent.resolve()

    print(f"Cartella dati    : {cartella}")
    print(f"Output salvati in: {script_dir}\n")

    if not cartella.exists():
        print(f"[ERRORE] Cartella non trovata: {cartella}")
        sys.exit(1)

    file_json = sorted(cartella.glob("*.json"))
    if not file_json:
        file_json = sorted(cartella.glob("**/*.json"))
        if file_json:
            print("[INFO] File .json trovati in sottocartelle.")
    if not file_json:
        print("[AVVISO] Nessun file .json trovato.")
        print(f"  Contenuto: {[p.name for p in cartella.iterdir()]}")
        sys.exit(0)

    print(f"File analizzati: {len(file_json)}\n")

    COL_NOME  = 45
    COL_DATA  = 22
    COL_CAUSA = 45
    SEP       = "-" * 160
    header    = (f"{'PAZIENTE':<{COL_NOME}} {'DATA DECESSO':<{COL_DATA}} "
                 f"{'CAUSA MORTE':<{COL_CAUSA}} SEGNALI FHIR")

    print(header)
    print(SEP)

    risultati = []

    for filepath in file_json:
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[SKIP] {filepath.name}: {e}")
            continue

        entries = data.get("entry", [])

        nome = "Sconosciuto"
        for entry in entries:
            if entry.get("resource", {}).get("resourceType") == "Patient":
                nome = estrai_nome(entry["resource"])
                break

        motivi, causa_morte = cerca_decesso(entries)

        if motivi:
            # Estrai data decesso dal segnale deceasedDateTime se presente
            data_decesso = ""
            for m in motivi:
                if m.startswith("deceasedDateTime:"):
                    data_decesso = m.split("deceasedDateTime:")[-1].strip()[:10]
                    break

            causa_str  = causa_morte if causa_morte else "non specificata"
            motivi_str = " | ".join(motivi)

            print(f"{nome:<{COL_NOME}} {data_decesso:<{COL_DATA}} {causa_str:<{COL_CAUSA}} {motivi_str}")
            risultati.append({
                "nome":         nome,
                "data_decesso": data_decesso,
                "causa_morte":  causa_str,
                "segnali":      motivi_str,
                "file":         filepath.name,
            })

    print(SEP)
    print(f"\nTotale deceduti trovati: {len(risultati)}")

    # Salva TXT nella cartella dello script
    output_file = script_dir / "deceduti.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Deceduti trovati: {len(risultati)}\n\n")
        f.write(header + "\n")
        f.write(SEP + "\n")
        for r in risultati:
            f.write(f"{r['nome']:<{COL_NOME}} {r['data_decesso']:<{COL_DATA}} "
                    f"{r['causa_morte']:<{COL_CAUSA}} {r['segnali']}\n")
        f.write(f"\n{SEP}\n")
        f.write("\nDETTAGLIO PER PAZIENTE\n")
        f.write(SEP + "\n")
        for r in risultati:
            f.write(f"\nPaziente   : {r['nome']}\n")
            f.write(f"Deceduto il: {r['data_decesso']}\n")
            f.write(f"Causa morte: {r['causa_morte']}\n")
            f.write(f"File       : {r['file']}\n")
            f.write(f"Segnali    : {r['segnali']}\n")

    print(f"Risultati salvati in: {output_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Utilizzo: python 1_trova_deceduti.py /percorso/cartella/fhir")
        sys.exit(1)
    analizza_cartella(sys.argv[1])
