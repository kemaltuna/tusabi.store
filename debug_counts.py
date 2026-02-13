import sys
import json
import logging

sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app")
from new_web_app.backend.routers.pdfs import get_all_manifests
from new_web_app.backend.routers.library import build_library_tree

logging.basicConfig(level=logging.ERROR)

print("--- DEBUGGING COUNTS ---")

manifests = get_all_manifests().get("subjects", {})
tree = build_library_tree(collapse_subtopics=True)

subject = "Patoloji"
print(f"\nComparing Subject: {subject}")

admin_total = 0
student_total = 0

if subject in manifests:
    for v in manifests[subject]["volumes"]:
        for s in v["segments"]:
            admin_total += s.get("question_count", 0)

if subject in tree:
    for cat_list in tree[subject]["categories"].values():
        for item in cat_list:
             student_total += item.get("count", 0)

print(f"Admin Count: {admin_total}")
print(f"Student Count: {student_total}")

if admin_total != student_total:
    print("\n--- Mismatch Details ---")
    admin_cats = {}
    for v in manifests[subject]["volumes"]:
        for s in v["segments"]:
            admin_cats[s["title"]] = admin_cats.get(s["title"], 0) + s.get("question_count", 0)
            
    student_cats = {}
    if subject in tree:
        for cat_name, items in tree[subject]["categories"].items():
            student_cats[cat_name] = sum(i.get("count", 0) for i in items)
            
    all_cats = set(admin_cats.keys()) | set(student_cats.keys())
    for c in sorted(all_cats):
        ac = admin_cats.get(c, 0)
        sc = student_cats.get(c, 0)
        if ac != sc:
             print(f"  '{c}': Admin={ac} vs Student={sc}")
