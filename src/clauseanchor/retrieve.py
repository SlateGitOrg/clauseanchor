"""BM25 retrieval over a contract's clauses, plus cross-reference and definition expansion."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .playbook import Issue
from .segment import Clause, Contract

_STOP = frozenset(
    "a an and any are as at be by for from has have in is it its of on or that the this to "
    "under with shall will may not no such other each".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")


def _stem(token: str) -> str:
    """Strip the commonest English suffixes so 'renews' and 'renewal' share a stem."""
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)] + replacement
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25:
    """Okapi BM25 with the non-negative idf variant, written from scratch."""

    def __init__(self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(documents)
        self.lengths = np.array([len(d) for d in documents], dtype=float)
        self.avg_len = float(self.lengths.mean()) if self.n else 0.0
        postings: dict[str, list[tuple[int, int]]] = {}
        for index, tokens in enumerate(documents):
            for term, tf in Counter(tokens).items():
                postings.setdefault(term, []).append((index, tf))
        self._postings = {
            term: (
                np.array([i for i, _ in entries], dtype=int),
                np.array([tf for _, tf in entries], dtype=float),
            )
            for term, entries in postings.items()
        }

    def idf(self, term: str) -> float:
        entry = self._postings.get(term)
        df = 0 if entry is None else len(entry[0])
        return math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, query: list[str]) -> np.ndarray:
        result = np.zeros(self.n)
        if self.n == 0 or self.avg_len == 0:
            return result
        for term in set(query):
            entry = self._postings.get(term)
            if entry is None:
                continue
            docs, tf = entry
            norm = self.k1 * (1.0 - self.b + self.b * self.lengths[docs] / self.avg_len)
            result[docs] += self.idf(term) * tf * (self.k1 + 1.0) / (tf + norm)
        return result


@dataclass(frozen=True)
class Retrieved:
    clause: Clause
    score: float
    reason: str  # "bm25", "xref" or "definition"


class Retriever:
    def __init__(self, contract: Contract, top_k: int = 5) -> None:
        self.contract = contract
        self.top_k = top_k
        self._bm25 = BM25([tokenize(self._index_text(c)) for c in contract.clauses])

    @staticmethod
    def _index_text(clause: Clause) -> str:
        return f"{clause.section} {clause.body}"

    def retrieve(self, issue: Issue) -> list[Retrieved]:
        """Top BM25 clauses for the issue hints, then what they cross-reference and define."""
        clauses = self.contract.clauses
        if not clauses:
            return []
        scores = self._bm25.scores(tokenize(" ".join(issue.hints)))
        order = np.argsort(-scores, kind="stable")[: self.top_k]
        picked = [Retrieved(clauses[i], float(scores[i]), "bm25") for i in order if scores[i] > 0]
        seen = {r.clause.number for r in picked}
        expanded: list[Retrieved] = []
        for hit in picked:
            for ref in self.contract.xrefs.get(hit.clause.number, []):
                target = self.contract.by_number[ref]
                if target.number not in seen:
                    seen.add(target.number)
                    expanded.append(Retrieved(target, 0.0, "xref"))
        for hit in [*picked, *expanded]:
            for term in self.contract.used_terms(hit.clause):
                definition = self.contract.by_number[self.contract.definitions[term].number]
                if definition.number not in seen:
                    seen.add(definition.number)
                    expanded.append(Retrieved(definition, 0.0, "definition"))
        return [*picked, *expanded]
