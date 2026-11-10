import datetime
import functools
import json
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
import webbrowser

import webview
from DataBase import DataBase   # il tuo DataBase.py, nella stessa cartella
from search_index import NameIndex

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)                  # DataBase usa percorsi relativi ("./nome")

DB_DIR = "databases"
REGISTRY = f"{DB_DIR}/registry.json"      # id del file (solo ASCII) -> nome mostrato
EXTRA = (".wal", ".shadow", ".lock")      # file collaterali creati da Kuzu
DEFAULT = "GraphDB"
NOTES = f"{DB_DIR}/notes.json"             # note sullo schema, per database


def _safe(fn):
    """Trasforma le eccezioni in {"ok": False, "error": ...} per l'interfaccia."""
    @functools.wraps(fn)
    def wrap(self, *a):
        with self._lock:                # una sola chiamata alla volta sul database
            try:
                return {"ok": True, **(fn(self, *a) or {})}
            except Exception as e:
                return {"ok": False, "error": str(e)}
    return wrap


def _human(n):
    for u in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} GB"


def _size(p):
    if os.path.isdir(p):
        return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
    return os.path.getsize(p)


def _when(t):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(t))


def _fileid(name):
    """Nome del file su disco: solo ASCII (Kuzu su Windows non gestisce bene gli accenti)."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()[:20] or "db"
    return f"{s}_{uuid.uuid4().hex[:6]}"


def _plain(v):
    """Valore Kuzu/pandas -> valore serializzabile in JSON."""
    if v is None:
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    return v if isinstance(v, (str, int, float, bool)) else str(v)


def _coerce(v, t):
    """Valore dall'interfaccia -> tipo della colonna. Vuoto = NULL."""
    if v is None or v == "":
        return None
    if t.startswith("INT"):
        return int(v)
    if t in ("DOUBLE", "FLOAT"):
        return float(v)
    if t == "BOOL":
        return v if isinstance(v, bool) else str(v).lower() in ("true", "1")
    if t == "DATE":
        return datetime.date.fromisoformat(str(v)[:10])
    if t == "TIMESTAMP":
        return datetime.datetime.fromisoformat(str(v))
    return str(v)


class Api:
    """Metodi pubblici = chiamabili dalla UI. Gli attributi privati iniziano con _."""

    def __init__(self):
        os.makedirs(DB_DIR, exist_ok=True)
        self._lock = threading.RLock()
        self._db = None
        self._ix = None              # indice dei nomi, costruito alla prima ricerca
        self._active = None          # nome mostrato del database aperto
        self._reg = self._load()
        names = self._names()
        if not names:
            self._new(DEFAULT)
        else:
            self._open(DEFAULT if DEFAULT in names else names[0])

    # ---------------------------- registro ---------------------------- #
    def _load(self):
        try:
            with open(REGISTRY, encoding="utf-8") as f:
                reg = json.load(f)
        except (FileNotFoundError, ValueError):
            reg = {}
        reg = {k: v for k, v in reg.items() if os.path.exists(f"{DB_DIR}/{k}")}
        for e in os.listdir(DB_DIR):   # adotta i database già presenti con nome ASCII
            if e.endswith(EXTRA) or e.endswith(".json") or e in reg or not e.isascii():
                continue
            reg[e] = e
        self._reg = reg
        self._save()
        return reg

    def _save(self):
        with open(REGISTRY, "w", encoding="utf-8") as f:
            json.dump(self._reg, f, ensure_ascii=False, indent=2)

    def _names(self):
        return sorted(self._reg.values(), key=str.lower)

    def _fid(self, name):
        for k, v in self._reg.items():
            if v == name:
                return k
        raise ValueError(f"Database «{name}» non trovato.")

    def _check(self, name):
        name = " ".join((name or "").split())
        if not 1 <= len(name) <= 50 or not name.isprintable():
            raise ValueError("Il nome deve avere da 1 a 50 caratteri.")
        if name.lower() in (n.lower() for n in self._names()):
            raise ValueError(f"Esiste già un database chiamato «{name}».")
        return name

    # ---------------------------- interni ---------------------------- #
    def _files(self, fid):
        base = f"{DB_DIR}/{fid}"
        return [p for p in (base, *(base + s for s in EXTRA)) if os.path.exists(p)]

    def _close(self):
        if self._db:
            self._db.stop()
        self._db, self._active, self._ix = None, None, None

    def _open(self, name):
        fid = self._fid(name)
        self._close()
        self._db = DataBase(name=f"{DB_DIR}/{fid}")
        self._active = name

    def _new(self, name):
        fid = _fileid(name)
        self._reg[fid] = name
        try:
            self._open(name)
        except Exception:
            del self._reg[fid]
            raise
        self._save()

    def _state(self):
        return {"names": self._names(), "active": self._active}

    def _counts(self):
        q = self._db._executeQueryRead
        tabs = q("CALL show_tables() RETURN *;")
        out = {"categorie di nodi": 0, "tipi di arco": 0, "nodi": 0, "archi": 0}
        for _, r in tabs.iterrows():
            if r["type"] == "NODE":
                out["categorie di nodi"] += 1
                out["nodi"] += int(q(f"MATCH (x:{r['name']}) RETURN count(x) AS c;")["c"].iloc[0])
            elif r["type"] == "REL":
                out["tipi di arco"] += 1
                out["archi"] += int(q(f"MATCH ()-[x:{r['name']}]->() RETURN count(x) AS c;")["c"].iloc[0])
        return out

    # ---------------------------- API UI ---------------------------- #
    @_safe
    def list_databases(self):
        return self._state()

    @_safe
    def open_database(self, name):
        self._open(name)
        return self._state()

    @_safe
    def create_database(self, name):
        self._new(self._check(name))
        return self._state()

    @_safe
    def rename_database(self, old, new):
        fid = self._fid(old)
        new = self._check(new) if new.lower() != old.lower() else " ".join(new.split())
        self._reg[fid] = new            # si cambia solo il nome mostrato: il file non si tocca
        self._save()
        if self._active == old:
            self._active = new
        return self._state()

    @_safe
    def delete_database(self, name):
        fid = self._fid(name)
        was_active = name == self._active
        if was_active:
            self._close()
        for p in self._files(fid):
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        del self._reg[fid]
        self._save()
        self._put_notes(fid, None)
        names = self._names()
        if not names:
            self._new(DEFAULT)          # c'è sempre almeno un database aperto
        elif was_active:
            self._open(names[0])
        return self._state()

    # ---------------------------- schema e note ---------------------------- #
    def _notes_all(self):
        try:
            with open(NOTES, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}

    def _put_notes(self, fid, notes):
        allx = self._notes_all()
        if notes:
            allx[fid] = notes
        else:
            allx.pop(fid, None)
        with open(NOTES, "w", encoding="utf-8") as f:
            json.dump(allx, f, ensure_ascii=False, indent=2)

    def _notes(self):
        return self._notes_all().get(self._fid(self._active), {})

    def _drop_notes(self, prefixes):
        notes = self._notes()
        for k in list(notes):
            if any(k == p or k.startswith(p + ".") for p in prefixes):
                del notes[k]
        self._put_notes(self._fid(self._active), notes)

    def _tables(self):
        df = self._db._executeQueryRead("CALL show_tables() RETURN *;")
        return set(df[df["type"] == "NODE"]["name"]), set(df[df["type"] == "REL"]["name"])

    @_safe
    def get_schema(self):
        raw = self._db.showSchema()
        nodes = {n: {"props": [{"name": p["name"], "type": p["type"], "pk": bool(p.get("primary key"))} for p in ps]}
                 for n, ps in raw["nodes"].items()}
        edges = {e: {"pairs": [[c["source table name"], c["destination table name"]] for c in d["connections"]],
                     "props": [{"name": p["name"], "type": p["type"]} for p in d["properties"]]}
                 for e, d in raw["edges"].items()}
        return {"schema": {"nodes": nodes, "edges": edges, "notes": self._notes()}}

    @_safe
    def schema_add_node(self, name):
        t = self._db._table(name)
        if t in set().union(*self._tables()):
            raise ValueError(f"«{t}» esiste già.")
        self._db.addNodeToSchema(name)
        return {"name": t}

    @_safe
    def schema_add_edge(self, name, text):
        t = self._db._table(name)
        nodes, rels = self._tables()
        if t in nodes | rels:
            raise ValueError(f"«{t}» esiste già.")
        pairs = []
        for line in re.split(r"[\n;,]+", text or ""):
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"\s*(?:->|→|>)\s*", line)
            if len(parts) != 2:
                raise ValueError(f"Coppia non valida: «{line}» (usa «Da > A»).")
            for x in parts:
                if self._db._table(x) not in nodes:
                    raise ValueError(f"La categoria «{x}» non esiste.")
            pairs.append(tuple(parts))
        if not pairs:
            raise ValueError("Indica almeno una coppia «Da > A».")
        self._db.addEdgeToSchema(name, pairs)
        return {"name": t}

    @_safe
    def schema_add_pair(self, edge, src, dst):
        e = self._db._table(edge)
        nodes, rels = self._tables()
        if e not in rels:
            raise ValueError(f"Il tipo di arco «{e}» non esiste.")
        a, b = self._db._table(src), self._db._table(dst)
        for x in (a, b):
            if x not in nodes:
                raise ValueError(f"La categoria «{x}» non esiste.")
        have = [(c["source table name"], c["destination table name"])
                for c in self._db.showSchema()["edges"][e]["connections"]]
        if (a, b) in have:
            raise ValueError(f"La coppia «{a} > {b}» esiste già.")
        self._db._executeQueryWrite(f"ALTER TABLE {e} ADD FROM {a} TO {b};")

    @_safe
    def schema_add_prop(self, table, prop, typ):
        t = self._db._table(table)
        p = self._db._validate_identifier((prop or "").strip())
        ty = self._db._validate_property_type(typ)
        self._db._executeQueryWrite(f"ALTER TABLE {t} ADD {p} {ty};")

    @_safe
    def schema_drop_prop(self, table, prop):
        t = self._db._table(table)
        p = self._db._validate_identifier(prop)
        if p in ("id", "nome"):
            raise ValueError("«id» e «nome» sono obbligatorie.")
        self._db._executeQueryWrite(f"ALTER TABLE {t} DROP {p};")
        self._drop_notes([f"node:{t}.{p}", f"edge:{t}.{p}"])

    @_safe
    def schema_drop_table(self, name):
        t = self._db._table(name)
        nodes, _ = self._tables()
        if t in nodes:
            edges = self._db.showSchema()["edges"]
            users = sorted(e for e, d in edges.items()
                           if any(t in (c["source table name"], c["destination table name"]) for c in d["connections"]))
            if users:
                raise ValueError("Prima elimina i tipi di arco che usano questa categoria: " + ", ".join(users) + ".")
        self._db.dropElementFromSchema(name)
        self._ix = None
        self._drop_notes([f"node:{t}", f"edge:{t}"])

    @_safe
    def schema_set_note(self, key, text):
        if not re.fullmatch(r"(node|edge):\w+(\.\w+)?", key or ""):
            raise ValueError("Chiave della nota non valida.")
        notes = self._notes()
        text = (text or "").strip()
        if text:
            notes[key] = text
        else:
            notes.pop(key, None)
        self._put_notes(self._fid(self._active), notes)

    # ---------------------------- dati (istanze) ---------------------------- #
    def _q(self, query, params=None):
        return self._db._executeQueryRead(query, params)

    def _types(self, table):
        df = self._q(f"CALL table_info('{self._db._table(table)}') RETURN *;")
        return {r["name"]: str(r["type"]).upper() for _, r in df.iterrows()}

    def _split(self, types, props):
        sets, nulls = {}, []
        for k, v in props.items():
            if k in ("id", "nome") or k not in types:
                raise ValueError(f"Proprietà «{k}» non modificabile o inesistente.")
            val = _coerce(v, types[k])
            if val is None:
                nulls.append(k)
            else:
                sets[k] = val
        return sets, nulls

    def _index(self):
        if self._ix is None:
            rows = []
            for t in sorted(self._tables()[0]):
                df = self._q(f"MATCH (n:{t}) RETURN n.id AS id, n.nome AS nome;")
                rows += [(t, r.id, r.nome) for r in df.itertuples()]
            self._ix = NameIndex(rows)
        return self._ix

    @_safe
    def warm_index(self):
        self._index()

    @_safe
    def search_nodes(self, text, limit=12):
        q = self._db._nome2id(text)
        out = []
        for c, i, n in self._index().search(q, int(limit)):
            node = self._db.getNode(c, i)
            if node is None:                     # indice non aggiornato: lo salto
                continue
            out.append({"cat": c, "id": i, "nome": n,
                        "props": {k: _plain(v) for k, v in node.items() if k not in ("categoria", "id", "nome")}})
        return {"hits": out}

    @_safe
    def sample_graph(self, limit=25):
        nt, rt = self._tables()
        nodes, edges = {}, {}
        per = max(3, int(limit) // max(1, len(nt)))
        for t in sorted(nt):
            for r in self._q(f"MATCH (n:{t}) RETURN n.id AS id, n.nome AS nome LIMIT {per};").itertuples():
                nodes[f"{t}:{r.id}"] = {"cat": t, "id": r.id, "nome": r.nome, "dist": 1}
        ids = [n["id"] for n in nodes.values()]
        for t in sorted(rt) if ids else []:
            e = self._q(f"MATCH (a)-[r:{t}]->(b) WHERE a.id IN $ids AND b.id IN $ids "
                        "RETURN label(a) AS ac, a.id AS aid, label(b) AS bc, b.id AS bid;", {"ids": ids})
            for r in e.itertuples():
                a, b = f"{r.ac}:{r.aid}", f"{r.bc}:{r.bid}"
                if a in nodes and b in nodes:
                    edges[f"{t}|{a}|{b}"] = {"src": a, "dst": b, "rel": t}
        return {"graph": {"nodes": list(nodes.values()), "edges": list(edges.values()), "center": None}}

    @_safe
    def neighborhood(self, cat, nid, depth=2, cap=60):
        """Nodi e archi fino a `depth` passi dal nodo, con al massimo `cap` nodi."""
        c0 = self._db._table(cat)
        center = self._db.getNode(c0, nid)
        if center is None:
            raise ValueError("Nodo non trovato.")
        k0 = f"{c0}:{nid}"
        nodes = {k0: {"cat": c0, "id": nid, "nome": center["nome"], "dist": 0}}
        edges, frontier = {}, [(c0, nid)]
        for d in range(1, int(depth) + 1):
            nxt = []
            for c, i in frontier:
                for r in self._db.getNeighbours(c, i):
                    k = f"{r['categoria']}:{r['id']}"
                    if k not in nodes:
                        if len(nodes) >= int(cap):
                            continue
                        nodes[k] = {"cat": r["categoria"], "id": r["id"], "nome": r["nome"], "dist": d}
                        nxt.append((r["categoria"], r["id"]))
                    a, b = (f"{c}:{i}", k) if r["direzione"] == "out" else (k, f"{c}:{i}")
                    edges[f"{r['arco']}|{a}|{b}"] = {"src": a, "dst": b, "rel": r["arco"]}
            frontier = nxt
        return {"graph": {"nodes": list(nodes.values()), "edges": list(edges.values()), "center": k0}}

    def _nbrs(self, cat, nid, cap=500):
        nb = self._db.getNeighbours(cat, nid)
        nb.sort(key=lambda r: (r["categoria"], (r["nome"] or "").lower()))
        keep = ("direzione", "arco", "categoria", "id", "nome")
        return {"neighbours": [{k: r[k] for k in keep} for r in nb[:cap]], "more": max(0, len(nb) - cap)}

    @_safe
    def get_node_detail(self, cat, nid):
        n = self._db.getNode(cat, nid)
        if n is None:
            raise ValueError("Nodo non trovato.")
        return {"node": {"cat": n["categoria"], "id": nid, "nome": n["nome"],
                         "props": {k: _plain(v) for k, v in n.items() if k not in ("categoria", "id", "nome")}},
                "types": self._types(cat), **self._nbrs(cat, nid)}

    @_safe
    def get_edge_detail(self, rel, sc, sid, dc, did):
        rt, st, dt = self._db._table(rel), self._db._table(sc), self._db._table(dc)
        df = self._q(f"MATCH (a:{st} {{id: $s}})-[r:{rt}]->(b:{dt} {{id: $d}}) RETURN r;", {"s": sid, "d": did})
        if df.empty:
            raise ValueError("Arco non trovato.")
        props = {k: _plain(v) for k, v in self._db._clean(df["r"].iloc[0]).items()}
        return {"edge": {"rel": rt, "sc": st, "sid": sid, "dc": dt, "did": did, "props": props,
                         "snome": self._db.getNode(st, sid)["nome"], "dnome": self._db.getNode(dt, did)["nome"]},
                "types": self._types(rt)}

    @_safe
    def add_node(self, cat, name):
        t, nid = self._db._table(cat), self._db._nome2id(name)
        if self._db.existNode(t, nid):
            raise ValueError(f"Esiste già un nodo con id «{nid}» in «{t}»: disambigua il nome, ad esempio «Mercurio (elemento)».")
        self._db.addNodeInstance(t, name.strip())
        if self._ix is not None:
            self._ix.add(t, nid, name.strip())
        return {"cat": t, "id": nid}

    @_safe
    def update_node(self, cat, nid, props):
        t = self._db._table(cat)
        sets, nulls = self._split(self._types(t), props)
        if sets:
            self._db.updateNodeInstance(t, nid, sets)
        for k in nulls:
            self._db._executeQueryWrite(
                f"MATCH (n:{t} {{id: $id}}) SET n.{self._db._validate_identifier(k)} = NULL;", {"id": nid})

    @_safe
    def delete_node(self, cat, nid):
        self._db.deleteNodeInstance(cat, nid)
        if self._ix is not None:
            self._ix.remove(self._db._table(cat), nid)

    @_safe
    def add_edge(self, rel, sc, sname, dc, dname):
        self._db.addEdgeInstance(rel, sc, sname, dc, dname)
        return {"cat": self._db._table(sc), "id": self._db._nome2id(sname)}

    @_safe
    def update_edge(self, rel, sc, sid, dc, did, props):
        sets, nulls = self._split(self._types(rel), props)
        if sets:
            self._db.updateEdge(rel, sc, sid, dc, did, sets)
        for k in nulls:
            self._db._executeQueryWrite(
                f"MATCH (a:{self._db._table(sc)} {{id: $s}})-[r:{self._db._table(rel)}]->(b:{self._db._table(dc)} {{id: $d}}) "
                f"SET r.{self._db._validate_identifier(k)} = NULL;", {"s": sid, "d": did})

    @_safe
    def delete_edge(self, rel, sc, sid, dc, did):
        self._db.deleteEdge(rel, sc, sid, dc, did)

    @_safe
    def open_url(self, url):
        if url.startswith(("http://", "https://", "mailto:")):
            webbrowser.open(url)

    @_safe
    def database_info(self, name):
        fid = self._fid(name)
        files = self._files(fid)
        info = {
            "Nome": name,
            "File": fid,
            "Percorso": os.path.abspath(f"{DB_DIR}/{fid}"),
            "Dimensione": _human(sum(_size(p) for p in files)),
            "Creato": _when(os.path.getctime(files[0])),
            "Modificato": _when(max(os.path.getmtime(p) for p in files)),
        }
        if name == self._active:
            info.update(self._counts())
        else:
            info["Contenuto"] = "apri il database per vedere nodi e archi"
        return {"info": info}


if __name__ == "__main__":
    api = Api()
    webview.create_window("NetLedge", "ui/index.html", js_api=api,
                          width=1200, height=760, min_size=(800, 500))
    webview.start()
    api._close()                        # rilascia il database alla chiusura
