"""Esporta l'arte di Jafta (riposo + volo Pegman) come webp per la WebUI.

Sorgenti: canvas QUADRATI 3000x3000 in questa cartella, disegnati
dall'artista gia' alla scala giusta e coerenti tra loro (personaggio della
stessa dimensione, teste allineate sul canvas). Qui NON si scala, NON si
ritaglia e NON si normalizza nulla: ogni webp e' il quadrato intero,
solo ridotto a SIZE x SIZE con lo stesso fattore per tutti (la scala
relativa tra le pose non viene mai toccata).

A runtime il layer di volo coincide esattamente col box del duo (tutte le
img sono width:100% del quadrato): l'unica costante calcolata qui a build
time e' il pivot della posa appesa — la punta della manica alzata (la
"mano"), misurata a mano sul canvas di jafta-hang.png perche' la sagoma
li' attorno e' ambigua (le ciocche superano la manica in altezza).

Output in jafta/templates/ui/assets/: jafta-{side,side-talk,hang,fall,
ground,walk1,walk2,hello1,hello2,idle}.webp, tutti SIZE x SIZE.

Il pensa e i quattro frame del parlato non si esportano piu': quello stato
adesso e' a due livelli (v. LAYERS sotto), e un webp che nessuno mostra
marcirebbe. I sorgenti restano in cartella: sono il riferimento con cui il
test della registrazione verifica che corpo + faccia ricompongano l'originale
(tests/webui/test_mascot_layer_sources.py). Nei sorgenti talk_* il numero
indica la bocca (1=aperta, 2=chiusa) e la lettera la posa (a=mano alzata,
b=braccia giu').

**Una variante per posa.** Fino al 08/09/2026 ogni posa esisteva in due
copie, line-art bianco/nero e colore, e il client rimappava il suffisso
-color su una preferenza dell'utente. La preferenza e' stata ritirata:
resta il colore, col nome piano.

**Due tabelle.** ``FILES`` sono le pose "cotte", con la faccia disegnata
dentro: le usano il docked, il volo e l'onboarding. ``LAYERS`` sono i
sorgenti a due livelli — corpi senza faccia e facce da sola — che la
companion sovrappone a mascotte intera.
Sono lo stesso canvas e lo stesso export: la composizione e' a runtime,
due <img> impilate, e qui non si compone niente.
"""
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parent
OUT = SRC.parent.parent / "jafta" / "templates" / "ui" / "assets"
SIZE = 768
QUALITY = 80

# Punta della manica alzata (la mano) sul canvas 3000x3000 di jafta-hang.png.
HAND_PIVOT = (1525, 1300)

FILES = [
    ("side", "jafta-side.PNG"),
    ("hang", "jafta-hang.PNG"),
    ("fall", "jafta-fall.PNG"),
    ("ground", "jafta-ground.PNG"),
    ("walk1", "jafta-walk1.PNG"),
    ("walk2", "jafta-walk2.PNG"),
    ("hello1", "hello1.PNG"),
    ("hello2", "hello2.PNG"),
    ("idle", "idle.PNG"),
    ("side-talk", "jafta-side-talk.PNG"),
]

# Sorgenti a due livelli, esportati come jafta-<stem con i trattini>.webp.
# Nome del file = cosa e': ``face_front_happy`` e' la faccia di **riposo**
# dell'espressione (per happy e' un sorriso a bocca aperta, ed e' giusto),
# ``_talk`` e' l'altra bocca. All'animatore del parlato serve la coppia, e
# l'ordine non si vede.
#
# Dal 28/09/2026 anche l'orientamento ``side`` per gli umori: al bordo, con
# un umore vivo, il corpo di lato senza faccia e la faccia dell'umore sopra.
#
# In cartella ci sono altri 10 sorgenti a livelli che qui NON si esportano:
# le bocche alternative degli umori, davanti e di lato (il parlato espressivo
# non c'e' ancora), la faccia di lato che pensa, il corpo di lato col gesto
# e i corpi del saluto. Un webp che nessuno puo' mostrare non va nel manifest
# e marcirebbe: quando servira', si aggiunge la riga qui.
LAYERS = [
    "body_front_idle",
    "body_front_hand",
    "body_front_think",
    "face_front_normal",
    "face_front_normal_talk",
    "face_front_thinking",
    "face_front_happy",
    "face_front_sad",
    "face_front_angry",
    "body_side_idle",
    "face_side_happy",
    "face_side_sad",
    "face_side_angry",
]


def _export(src_png: Path, dest: Path) -> None:
    """Ridimensiona un sorgente 3000x3000 a SIZE x SIZE e salva in webp."""
    im = Image.open(src_png).convert("RGBA")
    assert im.size == (3000, 3000), f"{src_png.name}: atteso canvas 3000x3000, trovato {im.size}"
    im.resize((SIZE, SIZE), Image.LANCZOS).save(dest, "WEBP", quality=QUALITY)
    print(f"{dest.name}: {dest.stat().st_size // 1024} KB")


if __name__ == "__main__":
    for name, png in FILES:
        _export(SRC / png, OUT / f"jafta-{name}.webp")
    for stem in LAYERS:
        _export(SRC / f"{stem}.PNG", OUT / f"jafta-{stem.replace('_', '-')}.webp")

    print(f"PIVOT_X = {HAND_PIVOT[0] / 3000:.4f}; PIVOT_Y = {HAND_PIVOT[1] / 3000:.4f}")
