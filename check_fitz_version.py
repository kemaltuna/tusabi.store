
import fitz
import sys

print(f"Python Version: {sys.version}")
print(f"PyMuPDF Version: {fitz.VersionBind}")

try:
    doc = fitz.open()
    page = doc.new_page()
    if hasattr(page, "find_tables"):
        print("✅ find_tables() is available!")
    else:
        print("❌ find_tables() is NOT available.")
except Exception as e:
    print(f"Error checking find_tables: {e}")
