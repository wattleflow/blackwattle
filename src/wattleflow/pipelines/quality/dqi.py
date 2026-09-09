# Module name: pipelines/quality/dqi.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# region docstr
"""
==============================================================================
Modul za mjerenje kvalitete podataka (Data Quality Index — DQI)
==============================================================================

Svrha
-----
Mjeri kvalitetu podataka u definiranim kontrolnim točkama (T1, T2, T3, ...)
kroz Wattleflow tok. Mjerenje je opservacijsko: ne mijenja podatke i ne
zaustavlja tok. Rezultati se pridružuju zapisu kao metapodaci i putuju s
njim do destinacije.

Standardi
---------
  - ISO/IEC 25012:2008 — Data Quality Model (definicija dimenzija).
  - ISO 8000-8:2015 — Information and data quality: Concepts and measuring
    (formula mjerenja kao omjer zapisa koji zadovoljavaju pravilo).
  - ISO 8000-61:2016 — Process reference model (procesni okvir za
    organizaciju kontrolnih točaka i odvajanje inherentne kvalitete
    izvora od kvalitete proizvoda nakon obrade).

Kontrolne točke
---------------
  T1  — sirovi podaci na ulazu (inherentna kvaliteta izvora).
  T2  — međurezultat poslije transformacija (može biti više: T2a, T2b, …).
  T3  — finalni podaci prije transfera (kvaliteta proizvoda).

Razlika DQI(T3) − DQI(T1) za isti zapis pokazuje neto učinak pipelinea.
Stopa zadržavanja |T3| / |T1| pokazuje koliki postotak zapisa preživljava
obradu.

Algoritmi
---------
Sve dimenzije vraćaju vrijednost u [0.0, 1.0]; konačni DQI je ponderirani
prosjek dimenzija (suma težina = 1.0):

    DQI = SUM(w_i * d_i)

Pojedinačne formule:

  Potpunost (Completeness)
    d = popunjena_obavezna_polja / ukupno_obaveznih_polja
    Prazno: None, prazan string, prazna lista.

  Valjanost (Validity)
    d = polja_koja_prolaze_pravila / ukupno_provjeravanih_polja
    Pravila: regex, raspon, format datuma, enumeracija.

  Dosljednost (Consistency)
    d = zadovoljena_cross_field_pravila / ukupno_cross_field_pravila
    (Koristiti AST evaluator umjesto ugrađenog eval.)

  Točnost (Accuracy)
    d = polja_podudarna_s_referencom / provjerena_polja
    Reference se dohvaćaju kroz ReadReferenceData strategiju.

  Aktualnost (Currentness)
    d = exp(-lambda * dob_u_satima)
    Eksponencijalno opadanje; lambda kontrolira brzinu starenja.

  Jedinstvenost (Uniqueness)
    d = 1.0 ako kombinacija ključnih polja nije viđena, inače 0.0
    Stanje (seen_keys) živi u blackboardu i dijeli se kroz tok.

Inkrementalno agregiranje
-------------------------
Za prosjek i varijancu DQI vrijednosti koristi se Welfordov on-line
algoritam — O(1) memorije, numerički stabilan:

    n     ← n + 1
    delta ← x − mean
    mean  ← mean + delta / n
    M2    ← M2 + delta * (x − mean)
    var   ← M2 / (n − 1)              (Besselova korekcija)

Agregati rastu zapis po zapis u blackboardu; izvještaj na kraju toka
samo čita gotove vrijednosti.

Konfigurabilnost
----------------
Modul je agnostičan u odnosu na konkretan standard. Promjenom YAML
konfiguracije (težine, pravila, pragovi) isti pipeline može mjeriti
kvalitetu prema različitim okvirima. Nove dimenzije dodaju se kao
plug-in funkcije u DQDimensionRegistry, bez izmjene jezgre.

Primjer korištenja
------------------
    aggregate = RunningAggregate()
    for record in dataset:
        score = compute_completeness(record, mandatory=["id", "amount"])
        aggregate.update(score)
    snapshot = aggregate.snapshot()    # {"count": ..., "mean": ..., ...}
==============================================================================
"""
# endregion docstr

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt
from typing import Any, Iterable, Optional
from wattleflow.helpers.dtime import Now

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Measuring for one record                                             #
# --------------------------------------------------------------------------- #


@dataclass
class DataQualityIndex:
    """
    Izmjereni indeks kvalitete (DQI) za pojedinačni zapis u zadanoj kontrolnoj
    točki — headline vrijednost ``dqi`` zajedno s razlaganjem po dimenzijama i
    prekršenim pravilima. Putuje s zapisom kroz facade.document.update_metadata.

    Polja:
      record_id     — identifikator zapisa (ako postoji u podacima)
      checkpoint    — oznaka kontrolne točke ("T1", "T2", "T3", ...)
      dqi           — konačni indeks kvalitete u [0.0, 1.0]
      dimensions    — pojedinačne ocjene po dimenziji u [0.0, 1.0]
      failed_rules  — popis pravila koja zapis nije zadovoljio
      timestamp     — vrijeme mjerenja (UTC)
    """

    record_id: str
    checkpoint: str
    dqi: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    failed_rules: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=Now.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "checkpoint": self.checkpoint,
            "dqi": round(self.dqi, 4),
            "dimensions": {k: round(v, 4) for k, v in self.dimensions.items()},
            "failed_rules": list(self.failed_rules),
            "timestamp": self.timestamp.isoformat(),
        }


# --------------------------------------------------------------------------- #
# endregion Measuring for one record                                          #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Welfordov inkrementalni agregator                                    #
# --------------------------------------------------------------------------- #


@dataclass
class RunningAggregate:
    """
    On-line agregator prosjeka, varijance, minimuma i maksimuma DQI
    vrijednosti kroz batch. Welfordov algoritam: O(1) memorije po
    pozivu update(), numerički stabilan.

    Koristi se kao stanje u blackboardu po kontrolnoj točki, npr.
    blackboard.read("dq:agg:T1") → RunningAggregate.

    Primjer:
        agg = RunningAggregate()
        for r in batch:
            agg.update(r.dqi, r.dimensions)
        agg.snapshot()  # {"count": ..., "mean": ..., "variance": ..., ...}
    """

    count: int = 0
    mean: float = 0.0
    _m2: float = 0.0  # akumulirana suma kvadrata odstupanja
    minimum: float = float("inf")
    maximum: float = float("-inf")

    # po dimenzijama — paralelni prosjek za svaku dimenziju
    dimension_means: dict[str, float] = field(default_factory=dict)
    _dimension_counts: dict[str, int] = field(default_factory=dict)

    def update(
        self,
        dqi: float,
        dimensions: Optional[dict[str, float]] = None,
    ) -> None:
        """Dodaje jednu DQI vrijednost u agregat."""
        # ukupna DQI vrijednost — Welford
        self.count += 1
        delta = dqi - self.mean
        self.mean += delta / self.count
        self._m2 += delta * (dqi - self.mean)
        self.minimum = min(self.minimum, dqi)
        self.maximum = max(self.maximum, dqi)

        # po dimenzijama — jednostavan inkrementalni prosjek
        if dimensions:
            for name, value in dimensions.items():
                cnt = self._dimension_counts.get(name, 0) + 1
                prev = self.dimension_means.get(name, 0.0)
                self.dimension_means[name] = prev + (value - prev) / cnt
                self._dimension_counts[name] = cnt

    @property
    def variance(self) -> float:
        """Varijanca s Besselovom korekcijom."""
        if self.count < 2:
            return 0.0
        return self._m2 / (self.count - 1)

    @property
    def stdev(self) -> float:
        """Standardna devijacija."""
        return sqrt(self.variance)

    def snapshot(self) -> dict[str, Any]:
        """Trenutni agregat kao serijabilan dict."""
        return {
            "count": self.count,
            "mean": round(self.mean, 4),
            "minimum": round(self.minimum, 4) if self.count else None,
            "maximum": round(self.maximum, 4) if self.count else None,
            "variance": round(self.variance, 4),
            "stdev": round(self.stdev, 4),
            "dimension_means": {k: round(v, 4) for k, v in self.dimension_means.items()},
        }


# --------------------------------------------------------------------------- #
# endregion Welfordov inkrementalni agregator                                 #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Prva dimenzija: Completeness (Potpunost)                             #
# --------------------------------------------------------------------------- #


def _is_empty(value: Any) -> bool:
    """
    Pravilo za prazne vrijednosti, primjenjivo na strukturirane podatke.
    Prazno znači: None, prazan string (i samo praznine), prazan iterabilni.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return len(value.strip()) == 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def compute_completeness(
    record: dict[str, Any],
    mandatory: Iterable[str],
    failed_rules: Optional[list[str]] = None,
) -> float:
    """
    Računa dimenziju potpunosti za jedan zapis.

      d = popunjena_obavezna_polja / ukupno_obaveznih_polja

    Argumenti:
      record        — zapis kao dict {polje: vrijednost}
      mandatory     — popis imena obaveznih polja
      failed_rules  — opcionalna lista u koju se dopisuju nezadovoljena
                      pravila u obliku "completeness:missing:<polje>"

    Vraća: vrijednost u [0.0, 1.0]. Ako popis obaveznih polja je prazan,
    vraća 1.0 (ništa što bi nedostajalo).
    """
    fields_required = list(mandatory)
    if not fields_required:
        return 1.0

    missing: list[str] = []
    for name in fields_required:
        if _is_empty(record.get(name)):
            missing.append(name)

    if failed_rules is not None:
        failed_rules.extend(f"completeness:missing:{name}" for name in missing)

    present = len(fields_required) - len(missing)
    return present / len(fields_required)


# --------------------------------------------------------------------------- #
# endregion Prva dimenzija: Completeness (Potpunost)                          #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Brza self-provjera (pokreni: python dq_evaluator.py)                 #
# --------------------------------------------------------------------------- #

# if __name__ == "__main__":
#     # 1. completeness na jednom zapisu
#     record = {
#         "transaction_id": "TX-0000000001",
#         "vehicle_id": "ZG1234AB",
#         "origin": "Zagreb",
#         "destination": "",  # prazno
#         "amount": 150.0,
#         "timestamp": None,  # nedostaje
#     }
#     mandatory = [
#         "transaction_id",
#         "vehicle_id",
#         "origin",
#         "destination",
#         "amount",
#         "timestamp",
#     ]
#     failed: list[str] = []
#     score = compute_completeness(record, mandatory, failed_rules=failed)
#     print(f"Completeness za jedan zapis: {score:.4f}")
#     print(f"Nezadovoljena pravila: {failed}")

#     # 2. agregat kroz mali batch
#     aggregate = RunningAggregate()
#     sample_dqi = [0.85, 0.92, 0.78, 0.95, 0.66, 0.88]
#     sample_dim = {"completeness": 0.9, "validity": 0.8}

#     for value in sample_dqi:
#         aggregate.update(value, sample_dim)

#     print(f"\nAgregat preko {len(sample_dqi)} zapisa:")
#     for key, val in aggregate.snapshot().items():
#         print(f"  {key}: {val}")

#     # 3. DataQualityIndex primjer
#     result = DataQualityIndex(
#         record_id="TX-0000000001",
#         checkpoint="T1",
#         dqi=score,
#         dimensions={"completeness": score},
#         failed_rules=failed,
#     )
#     print(f"\nDataQualityIndex.to_dict():")
#     for key, val in result.to_dict().items():
#         print(f"  {key}: {val}")

# --------------------------------------------------------------------------- #
# endregion Brza self-provjera (pokreni: python dq_evaluator.py)              #
# --------------------------------------------------------------------------- #
