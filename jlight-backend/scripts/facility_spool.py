"""Local SQLite spool for facility-side store-and-forward to JLIGHT.

Only use with approved synthetic data until a facility privacy/security review is complete.
Protect the spool file with OS permissions and encrypted storage; it may contain health data.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sqlite3, time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCHEMA = """
CREATE TABLE IF NOT EXISTS spool (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 idempotency_key TEXT NOT NULL UNIQUE,
 source_system TEXT NOT NULL,
 domain TEXT NOT NULL,
 export_format TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sent')),
 attempts INTEGER NOT NULL DEFAULT 0,
 last_error TEXT,
 created_at INTEGER NOT NULL,
 sent_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_spool_pending ON spool(status,id);
"""

def connect(path: str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p, ), timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript(SCHEMA)
    return db

def enqueue(db: sqlite3.Connection, *, source_system: str, domain: str,
            export_format: str, payload: object, idempotency_key: str | None = None) -> str:
    if domain not in {"hospital","laboratory","bioinformatics"}:
        raise ValueError("unsupported domain; Clinical Trials uses a separate workflow")
    if export_format not in {"fhir","hl7v2","csv"}:
        raise ValueError("format must be fhir, hl7v2 or csv")
    if not source_system.strip() or payload is None:
        raise ValueError("source_system and payload are required")
    canonical = json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    key = idempotency_key or hashlib.sha256((source_system+"\n"+domain+"\n"+export_format+"\n"+canonical).encode()).hexdigest()
    try:
        db.execute("INSERT INTO spool(idempotency_key,source_system,domain,export_format,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                   (key,source_system.strip(),domain,export_format,canonical,int(time.time())))
        db.commit()
    except sqlite3.IntegrityError:
        row=db.execute("SELECT source_system,domain,export_format,payload_json FROM spool WHERE idempotency_key=?",(key,)).fetchone()
        if row != (source_system.strip(),domain,export_format,canonical):
            raise ValueError("idempotency key reused with different content; manual review required")
    return key

def replay(db: sqlite3.Connection, *, api_base_url: str, token: str, organization_id: str,
           timeout: int = 15, max_items: int = 50) -> dict:
    if not api_base_url.startswith("https://"):
        raise ValueError("api_base_url must use HTTPS")
    if not token or not organization_id:
        raise ValueError("JLIGHT_ACCESS_TOKEN and JLIGHT_ORGANIZATION_ID are required")
    rows=db.execute("SELECT id,idempotency_key,source_system,domain,export_format,payload_json FROM spool WHERE status='pending' ORDER BY id LIMIT ?",(max_items,)).fetchall()
    sent,failed=0,0
    for row in rows:
        item_id,key,source,domain,fmt,payload_json=row
        body=json.dumps({"idempotency_key":key,"source_system":source,"domain":domain,"format":fmt,"payload":json.loads(payload_json)}).encode()
        req=Request(api_base_url.rstrip("/")+"/api/connectors/queue",data=body,method="POST",headers={
            "Authorization":"Bearer "+token,"X-JLIGHT-Organization":organization_id,
            "Idempotency-Key":key,"Content-Type":"application/json","Accept":"application/json"})
        try:
            with urlopen(req,timeout=timeout) as response:
                if response.status not in (200,201,202):
                    raise RuntimeError("unexpected HTTP status "+str(response.status))
                db.execute("UPDATE spool SET status='sent',attempts=attempts+1,last_error=NULL,sent_at=? WHERE id=?",(int(time.time()),item_id))
                db.commit()
                sent+=1
        except (HTTPError,URLError,TimeoutError,OSError,RuntimeError) as exc:
            db.execute("UPDATE spool SET attempts=attempts+1,last_error=? WHERE id=?",(type(exc).__name__,item_id))
            db.commit()
            failed+=1
            # Preserve ordering; don't hammer a failing or unreachable destination.
            break
    remaining=db.execute("SELECT COUNT(*) FROM spool WHERE status='pending'").fetchone()[0]
    return {"sent":sent,"failed":failed,"pending":remaining}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",default=os.environ.get("JLIGHT_SPOOL_DB","./jlight-spool.sqlite3"))
    sub=parser.add_subparsers(dest="command",required=True)
    add=sub.add_parser("enqueue")
    add.add_argument("--source-system",required=True); add.add_argument("--domain",required=True,choices=sorted({"hospital","laboratory","bioinformatics"}))
    add.add_argument("--format",required=True,choices=["fhir","hl7v2","csv"]); add.add_argument("--file",required=True)
    add.add_argument("--idempotency-key")
    rp=sub.add_parser("replay"); rp.add_argument("--max-items",type=int,default=50)
    args=parser.parse_args()
    with connect(args.db) as db:
        if args.command=="enqueue":
            payload=json.loads(Path(args.file).read_text(encoding="utf-8"))
            key=enqueue(db,source_system=args.source_system,domain=args.domain,export_format=args.format,payload=payload,idempotency_key=args.idempotency_key)
            print(json.dumps({"queued":True,"idempotency_key":key}))
        else:
            result=replay(db,api_base_url=os.environ.get("JLIGHT_API_BASE_URL",""),token=os.environ.get("JLIGHT_ACCESS_TOKEN",""),organization_id=os.environ.get("JLIGHT_ORGANIZATION_ID",""),max_items=args.max_items)
            print(json.dumps(result))
            raise SystemExit(1 if result["failed"] else 0)

if __name__=="__main__":
    main()
