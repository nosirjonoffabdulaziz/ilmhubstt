// Kichik IndexedDB yordamchisi: bulut ishlari, xulosalar va lokal fayl nusxalari shu brauzerda saqlanadi.
const DB = "ilmhubstt";
const VER = 1;
export type Store = "jobs" | "blobs" | "summaries";

let dbp: Promise<IDBDatabase> | null = null;
const mem: Record<Store, Map<string, any>> = { jobs: new Map(), blobs: new Map(), summaries: new Map() };
let broken = false;

function open(): Promise<IDBDatabase> {
  if (dbp) return dbp;
  dbp = new Promise((resolve, reject) => {
    let req: IDBOpenDBRequest;
    try { req = indexedDB.open(DB, VER); } catch (e) { reject(e); return; }
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const s of ["jobs", "blobs", "summaries"]) if (!db.objectStoreNames.contains(s)) db.createObjectStore(s);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(new Error("idb blocked"));
  });
  dbp.catch(() => { broken = true; });
  return dbp;
}

async function tx<T>(store: Store, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise<T>((resolve, reject) => {
    const t = db.transaction(store, mode);
    const r = fn(t.objectStore(store));
    t.oncomplete = () => resolve(r.result);
    t.onerror = () => reject(t.error || r.error);
    t.onabort = () => reject(t.error || new Error("aborted"));
  });
}

export async function idbGet<T = any>(store: Store, key: string): Promise<T | undefined> {
  if (!broken) {
    try { return await tx<T>(store, "readonly", (s) => s.get(key) as IDBRequest<T>); } catch { broken = true; }
  }
  return mem[store].get(key);
}
export async function idbPut(store: Store, key: string, value: any): Promise<void> {
  if (!broken) {
    try { await tx(store, "readwrite", (s) => s.put(value, key)); return; } catch (e) {
      if ((e as DOMException)?.name === "QuotaExceededError") throw e;
      broken = true;
    }
  }
  mem[store].set(key, value);
}
export async function idbDel(store: Store, key: string): Promise<void> {
  mem[store].delete(key);
  if (!broken) { try { await tx(store, "readwrite", (s) => s.delete(key)); } catch { /* */ } }
}
export async function idbClear(): Promise<void> {
  for (const s of ["jobs", "blobs", "summaries"] as Store[]) {
    mem[s].clear();
    if (!broken) { try { await tx(s, "readwrite", (st) => st.clear()); } catch { /* */ } }
  }
}
