#!/usr/bin/env python
import collections
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import core


def _count_entries(bucket):
    counts = collections.Counter()
    if core.DATA_FORMAT == "normalized_v2":
        for key, pairs in bucket.items():
            counts[key] += len(pairs)
    else:
        for key, items in bucket.items():
            counts[key] += len(items)
    return counts


def _find_variant_conflicts(mapping):
    seen = {}
    conflicts = collections.defaultdict(set)
    for canon, variants in mapping.items():
        for v in variants:
            prev = seen.get(v)
            if prev and prev != canon:
                conflicts[v].update({prev, canon})
            else:
                seen[v] = canon
    return conflicts


def main():
    print("=== Datos cargados ===")
    print(f"Formato detectado: {core.DATA_FORMAT}")
    print(f"Programas: {len(core.BY_CODE)}")

    if core.DATA_FORMAT == "normalized_v2":
        offer_count = sum(len(prog.get("ofertas") or []) for prog in core.BY_CODE.values())
    else:
        offer_count = sum(len(v) for v in core.BY_CODE.values())
    print(f"Ofertas totales: {offer_count}")

    print("\n=== Métricas de ubicación ===")
    mun_counts = _count_entries(core.BY_MUNICIPIO)
    sede_counts = _count_entries(core.BY_SEDE)
    print(f"Municipios indexados: {len(mun_counts)}")
    print(f"Sedes indexadas: {len(sede_counts)}")
    print("Top 5 municipios por ofertas:")
    for muni, count in mun_counts.most_common(5):
        print(f"  - {muni}: {count}")
    print("Top 5 sedes por ofertas:")
    for sede, count in sede_counts.most_common(5):
        print(f"  - {sede}: {count}")

    print("\n=== Validaciones de alias/sinónimos ===")
    for label, mapping in (
        ("topic_synonyms", core._TOPIC_SYNONYMS),
        ("sede_aliases_v2", core.SEDE_ALIASES_V2),
        ("alias_municipio", core.ALIAS_MUNICIPIO),
        ("alias_sede", core.ALIAS_SEDE),
    ):
        conflicts = _find_variant_conflicts(mapping)
        if conflicts:
            print(f"Conflictos en {label}:")
            for variant, canons in conflicts.items():
                canons_list = ", ".join(sorted(canons))
                print(f"  - '{variant}' compartido por {canons_list}")
        else:
            print(f"Sin conflictos de variantes en {label}.")


if __name__ == "__main__":
    main()
