FROM python:3.12-slim

# LibreOffice (Word/Excel/PPT -> PDF, aynan Word'ning o'zi qilgandek) va
# Tesseract OCR (faqat skanerlangan PDF'lar uchun, o'zbek+rus+ingliz tillari)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    tesseract-ocr \
    tesseract-ocr-uzb \
    tesseract-ocr-uzb-cyrl \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render bu portni beradi (PORT env orqali); shu yerda 10000 - standart
EXPOSE 10000

CMD ["python3", "pdf.py"]
