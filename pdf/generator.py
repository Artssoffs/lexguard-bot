from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from security.rsa_signing import sign_data
import hashlib

def generate_pdf(data: dict, file_path: str):
    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph(f"ID: {data['id']}", styles["Normal"]))
    content.append(Paragraph(f"Wallet: {data['wallet']}", styles["Normal"]))
    content.append(Paragraph(f"Risk: {data['risk']}", styles["Normal"]))

    data_string = f"{data['id']}|{data['wallet']}|{data['risk']}"
    signature = sign_data(data_string)

    content.append(Paragraph(f"Signature: {signature}", styles["Normal"]))

    doc.build(content)

    with open(file_path, "rb") as f:
        pdf_hash = hashlib.sha256(f.read()).hexdigest()

    return signature, pdf_hash
