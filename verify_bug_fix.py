
try:
    from new_web_app.core.gemini_client import construct_system_prompt_blocks
    prompt = construct_system_prompt_blocks(["foo"])
    print("SUCCESS: Prompt constructed successfully")
    print(prompt[-300:]) # Print tail to verify JSON part
except Exception as e:
    print(f"FAILED: {e}")
