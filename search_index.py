"""Indice in memoria dei nomi (categoria, id, nome) per ricerche veloci, anche con errori di battitura.

- prefissi:     lista ordinata + bisezione                     O(log n)
- sottostringhe e nomi simili: indice di trigrammi (tre lettere) O(candidati), non O(n)
"""
import bisect
import difflib
from collections import Counter, defaultdict


def _grams(s):
    s = f"  {s} "                      # il padding fa contare anche inizio e fine parola
    return {s[i:i + 3] for i in range(len(s) - 2)}


class NameIndex:
    def __init__(self, rows=()):
        self.items = {}                 # "cat:id" -> (cat, id, nome)
        self.post = defaultdict(set)    # trigramma -> insieme di chiavi
        self.sorted = []                # [(id, chiave)] ordinata, per i prefissi
        for cat, i, nome in rows:
            k = self._put(cat, i, nome)
            if k:
                self.sorted.append((i, k))
        self.sorted.sort()

    def __len__(self):
        return len(self.items)

    def _put(self, cat, i, nome):
        k = f"{cat}:{i}"
        if k in self.items:
            return None
        self.items[k] = (cat, i, nome)
        for g in _grams(i):
            self.post[g].add(k)
        return k

    def add(self, cat, i, nome):
        k = self._put(cat, i, nome)
        if k:
            bisect.insort(self.sorted, (i, k))

    def remove(self, cat, i):
        k = f"{cat}:{i}"
        if self.items.pop(k, None) is None:
            return
        for g in _grams(i):
            self.post[g].discard(k)
        j = bisect.bisect_left(self.sorted, (i, k))
        if j < len(self.sorted) and self.sorted[j] == (i, k):
            del self.sorted[j]

    def search(self, q, limit=12):
        """Restituisce fino a `limit` tuple (cat, id, nome), dalla più alla meno vicina a `q`."""
        scores = {}

        # 1) nome esatto e prefissi
        j = bisect.bisect_left(self.sorted, (q, ""))
        while j < len(self.sorted) and self.sorted[j][0].startswith(q) and len(scores) < 500:
            i, k = self.sorted[j]
            scores[k] = 2 + len(q) / len(i)
            j += 1

        # 2) sottostringhe
        if len(scores) < limit:
            if len(q) >= 3:
                sets = sorted((self.post.get(q[x:x + 3], set()) for x in range(len(q) - 2)), key=len)
                cand = set.intersection(*sets)
            else:
                cand = self.items.keys()
            for k in cand:
                if k not in scores and q in self.items[k][1]:
                    scores[k] = 1 + len(q) / len(self.items[k][1])

        # 3) nomi simili (errori di battitura): voto per trigrammi in comune, poi rifinisco i migliori
        if len(scores) < limit:
            votes = Counter()
            for g in _grams(q):
                for k in self.post.get(g, ()):
                    votes[k] += 1
            for k, _ in votes.most_common(300):
                if k not in scores:
                    r = difflib.SequenceMatcher(None, q, self.items[k][1]).ratio()
                    if r >= 0.4:
                        scores[k] = r

        top = sorted(scores.items(), key=lambda kv: (-kv[1], self.items[kv[0]][1]))[:limit]
        return [self.items[k] for k, _ in top]
