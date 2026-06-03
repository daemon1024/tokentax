"""Drain baseline — the zero-LLM-token cost floor.

Mines log templates with Drain3, turns each trace into a template-occurrence vector, and fits a
LogisticRegression. Token cost is exactly 0; we record wall-clock fit/predict time. This is the
floor the LLM/RLM methods must justify their token spend against — not a contender.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import numpy as np
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression

_HEX = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_NUM = re.compile(r"\b\d+\b")


def _normalize(line: str) -> str:
    """Light pre-masking so templates don't explode on ids/numbers (TraceID already scrubbed)."""
    line = _HEX.sub("<HEX>", line)
    line = _NUM.sub("<NUM>", line)
    return line.strip()


def _make_miner(sim_th: float = 0.4, depth: int = 4) -> TemplateMiner:
    cfg = TemplateMinerConfig()
    cfg.drain_sim_th = sim_th
    cfg.drain_depth = depth
    cfg.profiling_enabled = False
    return TemplateMiner(config=cfg)


@dataclass
class DrainResult:
    y_pred: list[int]
    n_templates: int
    fit_ms: float
    predict_ms: float


class DrainClassifier:
    """Fit/predict over objects exposing ``.records`` (or ``.lines``) and an int ``.label``."""

    name = "drain"

    def __init__(self, sim_th: float = 0.4, depth: int = 4):
        self.miner = _make_miner(sim_th, depth)
        self.clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        self.index: dict[int, int] = {}

    @staticmethod
    def _lines(example) -> list[str]:
        if hasattr(example, "records"):
            return [r.to_plain() for r in example.records]
        return list(getattr(example, "lines", []))

    def _vectorize(self, examples) -> csr_matrix:
        data: list[int] = []
        indices: list[int] = []
        indptr: list[int] = [0]
        for ex in examples:
            counts: dict[int, int] = {}
            for ln in self._lines(ex):
                cluster = self.miner.match(_normalize(ln), full_search_strategy="fallback")
                if cluster is not None and cluster.cluster_id in self.index:
                    j = self.index[cluster.cluster_id]
                    counts[j] = counts.get(j, 0) + 1
            for j, c in counts.items():
                indices.append(j)
                data.append(c)
            indptr.append(len(indices))
        n_features = max(1, len(self.index))
        return csr_matrix(
            (data, indices, indptr), shape=(len(examples), n_features), dtype=float
        )

    def fit(self, train) -> None:
        t0 = time.perf_counter()
        for ex in train:                       # mine templates on training lines only
            for ln in self._lines(ex):
                self.miner.add_log_message(_normalize(ln))
        cluster_ids = sorted(c.cluster_id for c in self.miner.drain.clusters)
        self.index = {cid: i for i, cid in enumerate(cluster_ids)}
        X = self._vectorize(train)
        y = np.array([ex.label for ex in train])
        self.clf.fit(X, y)
        self._fit_ms = (time.perf_counter() - t0) * 1000

    def predict(self, test) -> DrainResult:
        t0 = time.perf_counter()
        X = self._vectorize(test)
        y_pred = self.clf.predict(X).astype(int).tolist()
        return DrainResult(
            y_pred=y_pred,
            n_templates=len(self.index),
            fit_ms=getattr(self, "_fit_ms", 0.0),
            predict_ms=(time.perf_counter() - t0) * 1000,
        )
