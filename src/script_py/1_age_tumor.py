"""
Script 2 - Correlazione Eta / Dimensione Tumore
Utilizzo: python 2_eta_tumore.py /percorso/cartella/fhir
"""

import json, sys, csv, io
from pathlib import Path
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Codice LOINC esatto per "Size.maximum dimension in Tumor"
# Usiamo SOLO il codice per evitare di matchare osservazioni simili (es. "Polyp size")
TUMOR_SIZE_LOINC = "21889-1"
TUMOR_SIZE_DISPLAY = "size.maximum dimension in tumor"  # fallback se codice assente
ANNO_RIFERIMENTO    = 2026


def estrai_nome(p):
    for n in p.get("name", []):
        if n.get("use") == "official":
            parts = n.get("prefix", []) + n.get("given", []) + [n.get("family", "")]
            return " ".join(parts).strip()
    if p.get("name"):
        n = p["name"][0]
        return (" ".join(n.get("given", [])) + " " + n.get("family", "")).strip()
    return "Sconosciuto"


def calcola_eta(birth_date_str):
    if not birth_date_str:
        return None
    try:
        parts = birth_date_str.split("-")
        nascita     = date(int(parts[0]), int(parts[1]) if len(parts)>1 else 1, int(parts[2]) if len(parts)>2 else 1)
        riferimento = date(ANNO_RIFERIMENTO, 1, 1)
        return riferimento.year - nascita.year - ((riferimento.month, riferimento.day) < (nascita.month, nascita.day))
    except (ValueError, IndexError):
        return None


def is_tumor_obs(resource):
    """Matcha SOLO 'Size.maximum dimension in Tumor' (LOINC 21889-1)."""
    for c in resource.get("code", {}).get("coding", []):
        if c.get("code", "") == TUMOR_SIZE_LOINC:
            return True
        # Fallback sul display esatto (es. file senza codice LOINC)
        if TUMOR_SIZE_DISPLAY in c.get("display", "").lower():
            return True
    return False


def estrai_tumor_size_cm(resource):
    """Estrae il valore e lo converte sempre in cm."""
    vq    = resource.get("valueQuantity", {})
    value = vq.get("value")
    unit  = (vq.get("unit") or vq.get("code") or "cm").lower().strip()
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    # Conversione unita'
    if unit == "mm":
        return value / 10.0
    elif unit in ("cm", ""):
        return value
    elif unit == "m":
        return value * 100.0
    else:
        # Unita' sconosciuta: restituisce il valore grezzo con warning
        print(f"  [WARN] Unita' tumore sconosciuta: '{unit}', valore grezzo: {value}")
        return value


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs)/n, sum(ys)/n
    num  = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    denx = sum((x-mx)**2 for x in xs)**0.5
    deny = sum((y-my)**2 for y in ys)**0.5
    return num/(denx*deny) if denx and deny else None


def analizza_cartella(cartella_str):
    cartella   = Path(cartella_str).resolve()
    script_dir = Path(__file__).parent.resolve()

    print(f"Cartella dati    : {cartella}")
    print(f"Output salvati in: {script_dir}\n")

    if not cartella.exists():
        print(f"[ERRORE] Cartella non trovata: {cartella}")
        sys.exit(1)

    file_json = sorted(cartella.glob("*.json")) or sorted(cartella.glob("**/*.json"))
    if not file_json:
        print("[AVVISO] Nessun file .json trovato.")
        print(f"  Contenuto: {[p.name for p in cartella.iterdir()]}")
        sys.exit(0)

    print(f"File analizzati: {len(file_json)}\n")

    righe = []

    for filepath in file_json:
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[SKIP] {filepath.name}: {e}")
            continue

        nome, eta, sizes = "Sconosciuto", None, []

        for entry in data.get("entry", []):
            r  = entry.get("resource", {})
            rt = r.get("resourceType", "")
            if rt == "Patient":
                nome = estrai_nome(r)
                eta  = calcola_eta(r.get("birthDate", ""))
            elif rt == "Observation" and is_tumor_obs(r):
                val_cm = estrai_tumor_size_cm(r)
                if val_cm is not None:
                    sizes.append(val_cm)

        if sizes:
            righe.append({"file": filepath.name, "nome": nome, "eta": eta,
                          "tumor_size_cm": max(sizes),
                          "tumor_size_media": round(sum(sizes) / len(sizes), 4),
                          "n_misurazioni": len(sizes)})

    # --- Stampa tabella ---
    print(f"{'PAZIENTE':<45} {'ETA':>5}  {'SIZE MAX (cm)':>14}  {'SIZE MEDIA (cm)':>16}  {'# mis.':>6}  FILE")
    print("-" * 140)
    for r in righe:
        eta_str = str(r["eta"]) if r["eta"] is not None else "N/D"
        print(f"{r['nome']:<45} {eta_str:>5}  {r['tumor_size_cm']:>14.2f}  {r['tumor_size_media']:>16.2f}  {r['n_misurazioni']:>6}  {r['file']}")
    print("-" * 140)
    print(f"\nPazienti con dato tumorale : {len(righe)}")
    print(f"File senza dato tumorale   : {len(file_json) - len(righe)}")

    # --- Statistiche popolazione ---
    if righe:
        media_globale = sum(r["tumor_size_cm"] for r in righe) / len(righe)
        min_size      = min(r["tumor_size_cm"] for r in righe)
        max_size      = max(r["tumor_size_cm"] for r in righe)
        print(f"\n--- STATISTICHE POPOLAZIONE ({len(righe)} pazienti) ---")
        print(f"  Media size tumore : {media_globale:.4f} cm")
        print(f"  Minimo            : {min_size:.4f} cm")
        print(f"  Massimo           : {max_size:.4f} cm")

    # --- Correlazione ---
    eta_val  = [r["eta"]           for r in righe if r["eta"] is not None]
    size_val = [r["tumor_size_cm"] for r in righe if r["eta"] is not None]
    r_val = None
    if len(eta_val) >= 2:
        r_val = pearson(eta_val, size_val)
        print(f"\nCorrelazione di Pearson (eta vs size tumore): {r_val:.4f}")
        forza = ("molto debole o assente" if abs(r_val) < 0.2 else
                 "debole"                 if abs(r_val) < 0.4 else
                 "moderata"               if abs(r_val) < 0.6 else
                 "forte"                  if abs(r_val) < 0.8 else
                 "molto forte")
        direzione = "positiva" if r_val >= 0 else "negativa"
        print(f"  => {forza} {direzione}")

    # --- CSV ---
    # Excel italiano usa la virgola come separatore decimale:
    # sostituiamo il punto con la virgola nei valori float
    righe_excel = []
    for r in righe:
        righe_excel.append({
            "file":              r["file"],
            "nome":              r["nome"],
            "eta":               r["eta"] if r["eta"] is not None else "",
            "tumor_size_cm":     str(round(r["tumor_size_cm"], 4)).replace(".", ","),
            "tumor_size_media":  str(round(r["tumor_size_media"], 4)).replace(".", ","),
            "n_misurazioni":     r["n_misurazioni"],
        })

    output_csv = script_dir / "tumore_eta.csv"
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "nome", "eta", "tumor_size_cm", "tumor_size_media", "n_misurazioni"], delimiter=";")
        writer.writeheader()
        writer.writerows(righe_excel)

        # Riga finale con le statistiche della popolazione
        if righe:
            media_globale = sum(r["tumor_size_cm"] for r in righe) / len(righe)
            min_size      = min(r["tumor_size_cm"] for r in righe)
            max_size      = max(r["tumor_size_cm"] for r in righe)
            writer.writerow({"file": "", "nome": "", "eta": "", "tumor_size_cm": "", "tumor_size_media": "", "n_misurazioni": ""})
            writer.writerow({
                "file":             "--- STATISTICHE POPOLAZIONE ---",
                "nome":             f"{len(righe)} pazienti",
                "eta":              "",
                "tumor_size_cm":    "",
                "tumor_size_media": "",
                "n_misurazioni":    "",
            })
            writer.writerow({
                "file":             "Media size tumore (cm)",
                "nome":             "",
                "eta":              "",
                "tumor_size_cm":    str(round(media_globale, 4)).replace(".", ","),
                "tumor_size_media": "",
                "n_misurazioni":    "",
            })
            writer.writerow({
                "file":             "Minimo size tumore (cm)",
                "nome":             "",
                "eta":              "",
                "tumor_size_cm":    str(round(min_size, 4)).replace(".", ","),
                "tumor_size_media": "",
                "n_misurazioni":    "",
            })
            writer.writerow({
                "file":             "Massimo size tumore (cm)",
                "nome":             "",
                "eta":              "",
                "tumor_size_cm":    str(round(max_size, 4)).replace(".", ","),
                "tumor_size_media": "",
                "n_misurazioni":    "",
            })
    print(f"\nCSV salvato in: {output_csv}")

    # --- Grafico ---
    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.rcParams["axes.unicode_minus"] = False

        fig, ax = plt.subplots(figsize=(12, 7))
        ax.scatter(eta_val, size_val, color="#2196F3", edgecolors="#0D47A1",
                   alpha=0.75, s=80, zorder=3, label="Pazienti")

        if r_val is not None and len(eta_val) >= 2:
            n  = len(eta_val)
            mx = sum(eta_val)/n
            my = sum(size_val)/n
            den = sum((x-mx)**2 for x in eta_val)
            slope = sum((x-mx)*(y-my) for x,y in zip(eta_val,size_val))/den if den else 0
            intercept = my - slope*mx
            x_line = [min(eta_val), max(eta_val)]
            y_line = [slope*x + intercept for x in x_line]
            ax.plot(x_line, y_line, color="#F44336", linewidth=2,
                    linestyle="--", label=f"Regressione lineare (r = {r_val:.3f})")

        ax.set_xlabel("Eta del paziente (anni)", fontsize=13)
        ax.set_ylabel("Size massimo tumore (cm)", fontsize=13)
        ax.set_title("Correlazione Eta vs Dimensione Tumore", fontsize=15, fontweight="bold")
        ax.legend(fontsize=11)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.set_xlim(min(eta_val)-3, max(eta_val)+3)
        ax.set_ylim(-0.2, max(size_val)+0.5)
        plt.tight_layout()

        output_png = script_dir / "grafico_eta_tumore.png"
        plt.savefig(output_png, dpi=150)
        plt.show()
        print(f"Grafico salvato in: {output_png}")

    except ImportError:
        print("\n[AVVISO] matplotlib non trovato. Installalo con: pip install matplotlib")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Utilizzo: python 2_eta_tumore.py /percorso/cartella/fhir")
        sys.exit(1)
    analizza_cartella(sys.argv[1])
