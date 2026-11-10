# NetLedge

**NetLedge** è un'applicazione desktop leggera e potente per la gestione e l'esplorazione di database a grafo locali. Sviluppata in Python, sfrutta **Kùzu** come motore di database a grafo incorporato e offre un'interfaccia grafica moderna grazie a **pywebview**.

---

## Caratteristiche Principali

* **Gestione Multi-Database:** Crea, apri, rinomina ed elimina facilmente più database locali salvati in una cartella dedicata (`databases/`).
* **Motore a Grafo (Kùzu):** Sfrutta la potenza di Kùzu per definire schemi flessibili di **Nodi** e **Archi** (relazioni), gestire proprietà tipizzate e query performanti.
* **Ricerca Avanzata e Intelligente (`NameIndex`):** Un indice in memoria basato su prefissi, sottostringhe e trigrammi (`difflib`) che permette ricerche rapide e tolleranti agli errori di battitura (fuzzy search).
* **Esplorazione del Grafo e dei Vicini:** Visualizza dettagli sui nodi, esplora i vicini (neighborhood) a profondità variabile e naviga tra le relazioni in modo intuitivo.
* **Interfaccia Desktop Nativa:** Grazie a `pywebview`, l'applicazione gira come un'app nativa desktop, integrando una comunicazione fluida tra Python e la UI (tramite API JSON-RPC).

---

## Struttura del Progetto

Il codice sorgente è organizzato nei seguenti moduli principali:

* **`app.py`**: Il cuore dell'applicazione. Gestisce il ciclo di vita della finestra (`pywebview`), il registro dei database (`registry.json`), le note di schema e l'esposizione delle API per l'interfaccia utente.
* **`DataBase.py`**: Wrapper orientato agli oggetti attorno a **Kùzu**. Gestisce la creazione dello schema, le convalide degli identificatori/tipi e le operazioni CRUD su nodi e archi.
* **`search_index.py`**: Implementa la classe `NameIndex` per indicizzare in memoria i nodi e consentire ricerche rapide anche in presenza di refusi o corrispondenze parziali.
* **`installations.py`**: Script di utilità per l'installazione automatica delle dipendenze richieste.

---

## Requisiti e Installazione

Il progetto richiede **Python 3.8+**. 

1. Clona il repository o scarica i file nella tua cartella locale:
   ```bash
   git clone [https://github.com/tuo-username/tuo-repo.git](https://github.com/tuo-username/tuo-repo.git)
   cd tuo-repo
