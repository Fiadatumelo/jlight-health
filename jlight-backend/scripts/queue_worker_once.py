"""Run one authenticated JLIGHT queue-processing cycle; schedule externally."""
from __future__ import annotations
import json, os, sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def main() -> int:
    base=os.environ.get("JLIGHT_API_BASE_URL","").rstrip("/")
    token=os.environ.get("JLIGHT_ACCESS_TOKEN","")
    org=os.environ.get("JLIGHT_ORGANIZATION_ID","")
    if not base.startswith("https://") or not token or not org:
        print("Require HTTPS JLIGHT_API_BASE_URL, JLIGHT_ACCESS_TOKEN and JLIGHT_ORGANIZATION_ID",file=sys.stderr)
        return 2
    body=json.dumps({"limit":int(os.environ.get("JLIGHT_WORKER_BATCH_SIZE","5"))}).encode()
    req=Request(base+"/api/connectors/queue/process",data=body,method="POST",headers={
      "Authorization":"Bearer "+token,"X-JLIGHT-Organization":org,
      "Content-Type":"application/json","Accept":"application/json"})
    try:
        with urlopen(req,timeout=int(os.environ.get("JLIGHT_WORKER_TIMEOUT","30"))) as response:
            result=json.loads(response.read().decode())
            print(json.dumps(result))
            return 0 if response.status==200 and result.get("success") else 1
    except (HTTPError,URLError,TimeoutError,OSError,ValueError) as exc:
        # Never print credentials or response bodies that might contain source data.
        print("Queue worker cycle failed: "+type(exc).__name__,file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
