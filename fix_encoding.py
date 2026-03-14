import codecs
import re

with open("app/index.html", "r", encoding="utf-8") as f:
    text = f.read()

# Try exact decoding reversal first on the whole text
try:
    # If the file was UTF-8 read as CP1252 and saved as UTF-8:
    # Convert back to CP1252 bytes, then decode as UTF-8
    reversed_text = text.encode("cp1252").decode("utf-8")
    with open("app/index.html", "w", encoding="utf-8") as f:
        f.write(reversed_text)
    print("Blanket decode/encode successful!")
    exit(0)
except Exception as e:
    print(f"Blanket decode failed: {e}. Falling back to manual replacements.")

# Targeted replacements for the symbols in the screenshot
replacements = {
    'â€”': '—',
    'Â·': '·',
    'âš¡': '⚡',
    'ðŸ›¡': '🛡️',
    'ðŸ¤–': '🤖',
    'âž¡': '➡',
    'âœ…': '✅',
    'ðŸ”Ž': '🔍',
    'ðŸ§': '🧠',
    'ðŸ“Š': '📊',
    'â†’': '→',
    'âœ–': '✖',
    'ðŸš§': '🚧',
    'â‡¤': '⇤',
    'ðŸ’°': '💰',
    'â€œ': '“',
    'â€': '”',
    'â€˜': '‘',
    'â€™': '’',
    'ðŸ›': '🛡',   # Partial shield
    'ðŸ”': '🔍',   # Partial mag
    'ðŸ’': '💡',   # Idea
    'ðŸ’¡': '💡', 
    'ðŸ“': '📊',   # Chart part
    'ðŸ§': '🧠',   # Brain part
    'ðŸ›¡ï¸': '🛡️',
    'ðŸ›¡ï¸': '🛡️',
    'ðŸ›¡': '🛡️',
    'ðŸ”Ž': '🔍',
    'ðŸ§ ': '🧠 ',
    'ðŸ“Š': '📊',
    'âš¡ï¸': '⚡',
    'âš¡': '⚡',
    'â‡¤': '⇥',
    'â€“': '–'
}

count = 0
for k, v in replacements.items():
    if k in text:
        count += text.count(k)
        text = text.replace(k, v)

with open("app/index.html", "w", encoding="utf-8") as f:
    f.write(text)

print(f"Made {count} targeted character replacements.")
