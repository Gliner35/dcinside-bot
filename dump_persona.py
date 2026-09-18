import json

paths = [
    ("MANE", r"C:\Users\starl\Downloads\dcinside_bot\dcinside_bot\config.json"),
    ("MAPLE", r"C:\Users\starl\OneDrive\문서\Default Project\dcinside_bot_maple\config.json"),
]

for tag, p in paths:
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        nick = d.get("bot_nickname", "")
        persona = d.get("persona", "")
        print("===== %s :: persona 전체 덤프 =====" % tag)
        print("bot_nickname:", nick)
        print("persona length:", len(persona))
        print("--- persona text ---")
        print(persona)
        print("--- END %s ---" % tag)
        print()
    except Exception as exc:
        print("===== %s 읽기 실패 =====" % tag)
        print(exc)
