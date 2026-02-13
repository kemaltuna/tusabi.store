import json
import sys
import os

# Mock paths
sys.path.append("/home/yusuf-kemal-tuna/medical_quiz_app")
from new_web_app.backend.routers.pdfs import get_all_manifests
from new_web_app.backend.routers.library import build_library_tree

print("Testing payload sizes...")

try:
    manifests = get_all_manifests()
    man_json = json.dumps(manifests)
    print(f"Manifests Payload Size: {len(man_json) / 1024 / 1024:.2f} MB")
except Exception as e:
    print(f"Manifests Error: {e}")

try:
    tree = build_library_tree(collapse_subtopics=True)
    tree_json = json.dumps(tree)
    print(f"Library Tree Payload Size: {len(tree_json) / 1024 / 1024:.2f} MB")
except Exception as e:
    print(f"Tree Error: {e}")
