from kuzu import Database, Connection
import re
from unicodedata import normalize, combining

class DataBase:

    # Globalmente definito per la validazione dei tipi di proprietà supportati da Kùzu
    VALID_PROPERTY_TYPES = {"STRING", "INT64", "DOUBLE", "BOOL", "DATE", "TIMESTAMP", "INT32", "INT16", "INT8"}
    SYMBOLS = {"<": " lt ", ">": " gt ", "≤": " le ", "≥": " ge ", "≠": " ne ", "∈": " in ", "⊂": " subset ", "∀": " forall ", "∃": " exists "}
    # ------------------------------------------------------------------------------- #
    #                                 CICLO DI VITA                                 
    # ------------------------------------------------------------------------------- # 


    def __init__(self, name: str = "GraphDB"):
        """
        Inizializza la connessione al database Kuzu.

        Attributi: .db, .conn
        """
        self.db = Database(f"./{name}")
        self.conn = Connection(self.db)

    def stop(self, verbose: bool = False):
        """
        Chiude in modo sicuro la connessione e il database Kùzu,
        rilasciando i file bloccati sul disco.
        """
        try:
            # Chiudi la connessione attiva
            if hasattr(self, 'conn') and self.conn is not None:
                self.conn.close()
                self.conn = None

            # Chiudi l'istanza del database
            if hasattr(self, 'db') and self.db is not None:
                self.db.close()
                self.db = None
                
            if verbose:
                print("Database Disconnesso.")

        except Exception as e:
            print(f"Errore durante la chiusura del database: {e}")
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


    # ------------------------------------------------------------------------------- #
    #                                 UTILITIES                                 
    # ------------------------------------------------------------------------------- # 

    
    def _nome2id(self, nome: str) -> str:
        """
        Converte un nome in un ID univoco.
        Sostituisce spazi e caratteri speciali con underscore e converte tutto in minuscolo.
        """

        nome = normalize("NFKD", nome.strip().lower())
        nome = "".join(c for c in nome if not combining(c))
        nome = re.sub(r'[\s]+', '_', re.sub(r'[^\w\s]', '', nome))

        if not nome:
            raise ValueError("Errore: Il nome fornito è vuoto o contiene solo caratteri non validi.")
        
        return nome

    def _validate_identifier(self, identifier: str) -> str:
        """
        Valida che un identificatore (tabella, proprietà) segua le regole standard
        e non contenga caratteri pericolosi o non validi per Cypher.
        """

        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', identifier):
            raise ValueError(
                f"Identificatore non valido: '{identifier}'. "
                "Deve iniziare con una lettera o underscore e contenere solo lettere, numeri o underscore."
            )

        return identifier

    def _table(self, nome: str) -> str:
        """Per categorie e tipi di arco: normalizza, poi valida."""
        return self._validate_identifier(self._nome2id(nome))


    def _validate_property_type(self, prop_type: str) -> str:
        """Valida che il tipo di proprietà appartenga alla whitelist supportata da Kùzu."""
        
        prop_type = prop_type.strip().upper()
        if prop_type not in self.VALID_PROPERTY_TYPES:
            raise ValueError(
                f"Tipo di proprietà non valido: '{prop_type}'. "
                f"Tipi consentiti: {', '.join(sorted(self.VALID_PROPERTY_TYPES))}"
            )
        return prop_type
    
    def _executeQueryWrite(self, query: str, params: dict = None, verbose: bool = False):
        try:
            if not params:
                self.conn.execute(query)
            else:
                self.conn.execute(query, parameters=params)
            
            if verbose:
                print(f"Query di scrittura eseguita con successo: {query}")
        except Exception as e:
            print(f"Errore durante l'esecuzione della query di scrittura: {e}")
            raise

    def _executeQueryRead(self, query: str, params: dict = None, verbose: bool = False):
        try:
            if not params:
                result = self.conn.execute(query)
            else:
                result = self.conn.execute(query, parameters=params)
            
            if verbose:
                print(f"Query di lettura eseguita con successo: {query}")
            
            return result.get_as_df()
        except Exception as e:
            print(f"Errore durante l'esecuzione della query di lettura: {e}")
            raise

    @staticmethod
    def _clean(record: dict) -> dict:
        """Toglie i campi interni di Kuzu (_id, _label, _src, _dst, ...)."""
        return {k: v for k, v in record.items() if not k.startswith("_")}
    
    def showSchema(self):
        """
        Restituisce un quadro completo dello schema:
        - Per i nodi: proprietà, tipo e chiave primaria.
        - Per gli archi: tabelle di origine (FROM), destinazione (TO) e proprietà.
        """
        tables_df = self._executeQueryRead("CALL show_tables() RETURN *;")
        
        node_tables = tables_df[tables_df['type'] == 'NODE']['name'].tolist()
        edge_tables = tables_df[tables_df['type'] == 'REL']['name'].tolist()
        
        schema = {"nodes": {}, "edges": {}}
        
        # 1. Raccogli dettagli nodi
        for node in node_tables:
            info_df = self._executeQueryRead(f"CALL table_info('{node}') RETURN *;")
            schema["nodes"][node] = info_df.to_dict(orient="records")
            
        # 2. Raccogli dettagli archi (connessioni e proprietà)
        for edge in edge_tables:
            conn_df = self._executeQueryRead(f"CALL show_connection('{edge}') RETURN *;")
            info_df = self._executeQueryRead(f"CALL table_info('{edge}') RETURN *;")
            
            # show_connection restituisce solitamente 'from table' e 'to table' (o simili a seconda della versione di Kùzu)
            schema["edges"][edge] = {
                "connections": conn_df.to_dict(orient="records"),
                "properties": info_df.to_dict(orient="records")
            }
            
        return schema
    # ------------------------------------------------------------------------------- #
    #                           METODI DI LETTURA NEL DATABASE                                 
    # ------------------------------------------------------------------------------- #


    def existNode(self, node_category: str, node_instance_name: str) -> bool:
        """
        Controlla se un nodo esiste nel database cercandolo per categoria e ID.
        """
        node_category = self._table(node_category)
        node_instance_name = self._nome2id(node_instance_name)

        query = f"MATCH (n:{node_category} {{id: $id}}) RETURN count(n) AS cnt;"
        result = self._executeQueryRead(query, params={"id": node_instance_name})

        return result['cnt'].iloc[0] > 0

    def existEdge(self, edge_category: str, source_node_category: str, source_node_name: str, target_node_category: str, target_node_name: str) -> bool:
        """
        Controlla se uno specifico arco esiste tra due nodi.
        """
        src_id = self._nome2id(source_node_name)
        tgt_id = self._nome2id(target_node_name)
        
        edge_category = self._table(edge_category)
        src_cat = self._table(source_node_category)
        tgt_cat = self._table(target_node_category)

        query = f"""
            MATCH (a:{src_cat} {{id: $src}})-[r:{edge_category}]->(b:{tgt_cat} {{id: $tgt}})
            RETURN count(r) AS cnt;
        """
        result = self._executeQueryRead(query, params={"src": src_id, "tgt": tgt_id})
        
        return result['cnt'].iloc[0] > 0
 
    def getNode(self, node_category: str, node_instance_name: str):
        """
        Restituisce il nodo come dizionario (con la chiave aggiuntiva 'categoria'),
        oppure None se non esiste.
        """
        cat = self._table(node_category)
        query = f"MATCH (n:{cat} {{id: $id}}) RETURN n;"
        df = self._executeQueryRead(query, params={"id": self._nome2id(node_instance_name)})
 
        if df.empty:
            return None
 
        node = df["n"].iloc[0]
        return {"categoria": node.get("_label", cat), **self._clean(node)}

    def getNeighbours(self, node_category: str, node_instance_name: str, edge_category: str = None, direction: str = "both") -> list:
        """
        Nodi a un arco di distanza. Restituisce una lista di dizionari:
            direzione ('out' / 'in'), arco, categoria, id, nome
        e, solo se `edge_category` è specificato, anche 'proprieta' (proprietà dell'arco).

        direction:
            'out'  -> archi che partono dal nodo      (nodo -> altro)
            'in'   -> archi che arrivano al nodo      (altro -> nodo)
            'both' -> entrambi (ogni riga dice da che parte è l'arco)

        Solleva ValueError se il nodo di partenza non esiste.
        """
        if direction not in ("out", "in", "both"):
            raise ValueError("direction deve essere 'out', 'in' o 'both'.")

        if not self.existNode(node_category, node_instance_name):
            raise ValueError(
                f"Errore: il nodo '{node_instance_name}' nella categoria '{node_category}' non esiste."
            )

        cat = self._table(node_category)
        rel = f":{self._table(edge_category)}" if edge_category else ""
        params = {"id": self._nome2id(node_instance_name)}

        patterns = {
            "out": f"(a:{cat} {{id: $id}})-[r{rel}]->(b)",
            "in":  f"(a:{cat} {{id: $id}})<-[r{rel}]-(b)",
        }

        # Le proprietà dell'arco le leggo solo quando il tipo di arco è fissato:
        # con più tabelle di relazione diverse le colonne non sarebbero omogenee.
        extra = ", r AS dati_arco" if edge_category else ""

        neighbours = []
        for d in (("out", "in") if direction == "both" else (direction,)):
            query = (
                f"MATCH {patterns[d]} "
                f"RETURN label(r) AS arco, label(b) AS categoria, b.id AS id, b.nome AS nome{extra};"
            )
            df = self._executeQueryRead(query, params=params)

            for row in df.to_dict(orient="records"):
                item = {"direzione": d, **row}
                if edge_category:
                    item["proprieta"] = self._clean(item.pop("dati_arco"))
                neighbours.append(item)

        return neighbours

    def move(self, node_category: str, node_instance_name: str, edge_category: str, direction: str = "both", target_category: str = None) -> list:
        """
        Parte da un nodo, segue un tipo di arco e restituisce i nodi di arrivo
        COMPLETI (tutte le proprietà). Ogni nodo ha in più la chiave 'via' con
        direzione e proprietà dell'arco percorso.

        Per concatenare i passaggi usa 'categoria' e 'nome' (o 'id') del risultato:
            for c in db.move("Risultato", "Weierstrass", "HA_IPOTESI"):
                db.move(c["categoria"], c["nome"], "HA_IPOTESI", direction="in")

        target_category: se l'arco collega più categorie di arrivo, filtra su una.
        """
        found = self.getNeighbours(node_category, node_instance_name, edge_category, direction)

        if target_category is not None:
            target = self._table(target_category)
            found = [n for n in found if n["categoria"] == target]

        nodes = []
        for n in found:
            node = self.getNode(n["categoria"], n["id"])   # una query per nodo: ok per un uso personale
            node["via"] = {"direzione": n["direzione"], **n["proprieta"]}
            nodes.append(node)

        return nodes


    # ------------------------------------------------------------------------------- #
    #                           METODI DI SCRITTURA NEL DATABASE                                 
    # ------------------------------------------------------------------------------- # 


    def addNodeToSchema(self, node_name: str, properties: dict = None):
        properties = dict(properties or {})

        # 'id' è una proprietà obbligatoria per i nodi
        if "id" not in properties:
            properties["id"] = "STRING"

        # 'nome' è una proprietà obbligatoria per i nodi
        if "nome" not in properties:
            properties["nome"] = "STRING"

        for prop_name, prop_type in properties.items():
            self._validate_identifier(prop_name)
            self._validate_property_type(prop_type)

        # Costruiamo le definizioni delle colonne (es. "id STRING, nome STRING, autore STRING")
        props_defs = [f"{prop_name} {prop_type}" for prop_name, prop_type in properties.items()]
        props_str = ", ".join(props_defs)

        # Pulisci nome, crea ed esegui la query
        node_name = self._table(node_name)
        
        query = f"CREATE NODE TABLE IF NOT EXISTS {node_name} ({props_str}, PRIMARY KEY(id));"
        self._executeQueryWrite(query)

    def addEdgeToSchema(self, edge_name, pairs, properties=None):
        edge_name = self._table(edge_name)
        pair_defs = ", ".join(f"FROM {self._table(a)} TO {self._table(b)}" for a, b in pairs)
        props = "".join(f", {self._validate_identifier(k)} {self._validate_property_type(t)}" for k, t in (properties or {}).items())
        self._executeQueryWrite(f"CREATE REL TABLE IF NOT EXISTS {edge_name} ({pair_defs}{props});")

    def dropElementFromSchema(self, el_name: str):
        query = f"DROP TABLE {self._table(el_name)};"
        self._executeQueryWrite(query)

    def addNodeInstance(self, node_category: str, node_instance_name: str, properties: dict = None):
        if properties is None:
            properties = {}

        RESERVED = {"id", "nome"}
        if RESERVED & properties.keys():
            raise ValueError("'id' e 'nome' sono gestiti internamente.")
        
        for key in properties.keys():
            self._validate_identifier(key)

        # Prepariamo il dizionario con l'id
        params = {"id": self._nome2id(node_instance_name), "nome": node_instance_name}
        node_category = self._table(node_category)

        # Costruiamo dinamicamente la stringa delle proprietà extra (es. description: $desc, year: $year)
        props_query_parts = ["id: $id", "nome: $nome"]
        for key, value in properties.items():
            param_key = f"p_{key}"
            params[param_key] = value
            props_query_parts.append(f"{key}: ${param_key}")

        props_str = ", ".join(props_query_parts)
        query = f"CREATE (n:{node_category} {{{props_str}}});"

        self._executeQueryWrite(query, params = params)

    def updateNodeInstance(self, node_category: str, node_instance_name: str, new_properties: dict):
        """
        Modifica le proprietà di un'istanza di nodo esistente cercandola per ID.
        `new_properties` è un dizionario con le chiavi e i nuovi valori da aggiornare.
        """
        if not new_properties:
            return

        RESERVED = {"id", "nome"}
        if RESERVED & new_properties.keys():
            raise ValueError("'id' e 'nome' sono gestiti internamente e non possono essere modificati direttamente.")
        
        if not self.existNode(node_category, node_instance_name):
            raise ValueError(f"Errore: Impossibile aggiornare. Il nodo '{node_instance_name}' nella categoria '{node_category}' non esiste.")
        
        for key in new_properties.keys():
            self._validate_identifier(key)

        set_parts = []
        params = {"id": self._nome2id(node_instance_name)}
        node_category = self._table(node_category)
        
        
        for key, value in new_properties.items():
            param_key = f"p_{key}"
            params[param_key] = value
            set_parts.append(f"n.{key} = ${param_key}")

        set_str = ", ".join(set_parts)
        query = f"MATCH (n:{node_category} {{id: $id}} ) SET {set_str};"

        self._executeQueryWrite(query, params = params)

    def deleteNodeInstance(self, node_category: str, node_instance_name: str):
        if not self.existNode(node_category, node_instance_name):
            raise ValueError(f"Errore: Impossibile eliminare. Il nodo '{node_instance_name}' nella categoria '{node_category}' non esiste.")
        
        node_category = self._table(node_category)
        node_instance_name = self._nome2id(node_instance_name)
        
        query = f"MATCH (n:{node_category} {{id: $id}}) DETACH DELETE n;"
        self._executeQueryWrite(query, params = {"id": node_instance_name})

    def addEdgeInstance(self, edge_category: str, source_node_category: str, source_node_name: str, target_node_category: str, target_node_name: str, properties: dict = None):
        """
        Crea un arco tra due nodi verificando prima l'esistenza di entrambi.
        Se l'arco esiste già, genera errore. Se un nodo manca, solleva un errore.
        """
        if properties is None:
            properties = {}

        if self.existEdge(edge_category, source_node_category, source_node_name, target_node_category, target_node_name):
            raise ValueError(f"L'arco '{edge_category}' tra '{source_node_name}' e '{target_node_name}' esiste già: per modificarlo usa updateEdge.")       
        
        for key in properties.keys():
            self._validate_identifier(key)

        src_id = self._nome2id(source_node_name)
        tgt_id = self._nome2id(target_node_name)
        
        edge_category = self._table(edge_category)
        src_cat = self._table(source_node_category)
        tgt_cat = self._table(target_node_category)

        # 1. Verifichiamo prima che il nodo sorgente esista
        if not self.existNode(src_cat, src_id):
            raise ValueError(f"Errore: Il nodo sorgente '{source_node_name}' nella categoria '{source_node_category}' non esiste.")

        # 2. Verifichiamo che il nodo destinazione esista
        if not self.existNode(tgt_cat, tgt_id):
            raise ValueError(f"Errore: Il nodo destinazione '{target_node_name}' nella categoria '{target_node_category}' non esiste.")
        
        params = {"src": src_id, "tgt": tgt_id}
        props_query_parts = []
        for key, value in properties.items():
            param_key = f"p_{key}"
            params[param_key] = value
            props_query_parts.append(f"{key}: ${param_key}")

        props_str = f" {{{', '.join(props_query_parts)}}}" if props_query_parts else ""
        
        query = f"""
                MATCH (a:{src_cat} {{id: $src}}), (b:{tgt_cat} {{id: $tgt}})
                CREATE (a)-[:{edge_category}{props_str}]->(b);
                """
        
        self._executeQueryWrite(query, params=params)


    def updateEdge(self, edge_category: str, source_node_category: str, source_node_name: str, target_node_category: str, target_node_name: str, new_properties: dict):
        if not new_properties:
            return

        if not self.existEdge(edge_category, source_node_category, source_node_name, target_node_category, target_node_name):
            raise ValueError(f"Errore: Impossibile aggiornare l'arco '{edge_category}' tra '{source_node_name}' e '{target_node_name}': l'arco non esiste.")
        
        for key in new_properties.keys():
            self._validate_identifier(key)
        
        set_parts = []
        params = {
            "src": self._nome2id(source_node_name), 
            "tgt": self._nome2id(target_node_name)
        }
        
        edge_category = self._table(edge_category)
        src_cat = self._table(source_node_category)
        tgt_cat = self._table(target_node_category)

        for key, value in new_properties.items():
            param_key = f"p_{key}"
            params[param_key] = value
            set_parts.append(f"r.{key} = ${param_key}")

        set_str = ", ".join(set_parts)
        query = f"""
            MATCH (a:{src_cat} {{id: $src}})-[r:{edge_category}]->(b:{tgt_cat} {{id: $tgt}})
            SET {set_str};
        """

        self._executeQueryWrite(query, params = params)

    def deleteEdge(self, edge_category: str, source_node_category: str, source_node_name: str, target_node_category: str, target_node_name: str):
        """Elimina uno specifico arco tra due nodi specificando le categorie."""

        if not self.existEdge(edge_category, source_node_category, source_node_name, target_node_category, target_node_name):
            raise ValueError(f"Errore: Impossibile eliminare l'arco '{edge_category}' tra '{source_node_name}' e '{target_node_name}': l'arco non esiste.")
        
        params = {
            "src": self._nome2id(source_node_name), 
            "tgt": self._nome2id(target_node_name)
        }
        
        edge_category = self._table(edge_category)
        src_cat = self._table(source_node_category)
        tgt_cat = self._table(target_node_category)

        query = f"""
            MATCH (a:{src_cat} {{id: $src}})-[r:{edge_category}]->(b:{tgt_cat} {{id: $tgt}})
            DELETE r;
        """

        self._executeQueryWrite(query, params = params)
    