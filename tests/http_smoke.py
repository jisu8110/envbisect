"""Default checks web security only; --live adds a paid Daytona cancellation check."""
import argparse
import sys
import time
import requests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true")
    parser.add_argument("--port",type=int,default=8000)
    args=parser.parse_args()
    base=f"http://127.0.0.1:{args.port}"
    state=requests.get(base+"/api/status",timeout=5).json()
    assert not state["active_id"], "Do not interrupt another active run"
    headers={"Origin":base,"X-EnvBisect-Token":state["csrf"]}
    for path in ("/.env","/config.py","/runs/anything","/../.env"):
        assert requests.get(base+path,timeout=5).status_code==404
    assert requests.get(base+"/api/status",headers={"Host":"untrusted.example"},timeout=5).status_code==403
    assert requests.post(base+"/api/start",json={},timeout=5).status_code==403
    assert requests.post(base+"/api/start",json={},headers={**headers,"Origin":"https://untrusted.example"},timeout=5).status_code==403
    assert requests.post(base+"/api/start",json={"shell":"not executable"},headers=headers,timeout=5).status_code==400
    for options in ({"backend":"local"},{"planner":"rules"},{"smoke":True},{"issue_url":"https://github.com/nodejs/node/issues/1"}):
        assert requests.post(base+"/api/start",json=options,headers=headers,timeout=5).status_code==400
    if not args.live:
        print({"security_checks":"PASS","daytona_llm_only":"PASS","paid_runs":0})
        return 0
    options={"max_worlds":2,"seconds":90}
    response=requests.post(base+"/api/start",json=options,headers=headers,timeout=5)
    assert response.status_code==202,response.text
    run_id=response.json()["run_id"]
    stopped=False
    deadline=time.monotonic()+180
    try:
        if args.live:
            assert requests.post(base+"/api/start",json=options,headers=headers,timeout=5).status_code==409
        while time.monotonic()<deadline:
            d=requests.get(base+"/api/run",params={"id":run_id},timeout=5).json()
            phases=[e["data"] for e in d["events"] if e["event"]=="world_phase"]
            if args.live and not stopped and any(e["phase"] in ("CREATED","UPLOADING") for e in phases):
                assert requests.post(base+"/api/stop",json={"run_id":run_id},headers=headers,timeout=5).status_code==202
                stopped=True
            if not d["active"]:
                assert d["summary"], d
                expected="CANCELLED" if args.live else "BASELINE_VERIFIED"
                assert d["status"]==expected,(d["status"],d["summary"].get("error"))
                created={e["sandbox_id"] for e in phases if e["phase"]=="CREATED"}
                deleted={e["sandbox_id"] for e in phases if e["phase"]=="DESTROYED"}
                assert created<=deleted,(created,deleted)
                downloaded=requests.get(base+"/api/evidence",params={"id":run_id},timeout=5)
                assert downloaded.status_code==200 and downloaded.json()["run_id"]==run_id
                assert "attachment" in downloaded.headers["Content-Disposition"]
                print({"run_id":run_id,"security_checks":"PASS","state":d["status"],"created":len(created),"deleted":len(deleted),"download":"PASS"})
                return 0
            time.sleep(0.2)
        raise RuntimeError("Integration test timed out")
    finally:
        requests.post(base+"/api/stop",json={"run_id":run_id},headers=headers,timeout=5)


if __name__=='__main__':sys.exit(main())
