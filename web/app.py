from fastapi import FastAPI
from security.rsa_signing import verify_signature

app = FastAPI()
db = {}

@app.get("/verify/{report_id}")
def verify(report_id: str):
    report = db.get(report_id)

    if not report:
        return {"status": "fake"}

    data_string = f"{report['id']}|{report['wallet']}|{report['risk']}"
    valid = verify_signature(data_string, report["signature"])

    return {
        "status": "valid" if valid else "tampered",
        "data": report
    }
